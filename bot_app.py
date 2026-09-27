"""
Точка входа для продакшна.
Запускает планировщик в фоне и Telegram-бот для модерации.

Цикл каждые N минут:
  1. Парсим hh.ru → фильтруем → сохраняем в БД
  2. Новые вакансии отправляем в чат модерации с кнопками

Бот слушает нажатия кнопок:
  ✅ Опубликовать → постит в канал, помечает 'posted'
  ❌ Отклонить    → помечает 'rejected'
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from telegram.error import Conflict
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

import config
import database
import scoring
from bot.alerts import check_balances, daily_report, money_report, send_alert
from bot.handlers import handle_edit_reply, handle_moderation
from bot.moderator import publish_due_scheduled, resend_due_snoozed, send_new_vacancies_to_moderation
from exporters.sheets import pull_returns
from scheduler import SLOW_PARSERS, run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# httpx логирует полные URL с токеном — отключаем
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# Стартовый и регулярный цикл — разные задачи планировщика, max_instances их не разводит.
# Замок гарантирует, что одновременно идёт один цикл.
_cycle_lock = threading.Lock()
_slow_cycle_lock = threading.Lock()
SLOW_CYCLE_HOURS = 6

# Поток с зависшим сетевым вызовом не убить — сторож гасит процесс, launchd (KeepAlive) поднимает.
# Лимит с запасом: ATS-цикл идёт ~2 часа.
CYCLE_TIMEOUT_HOURS = {"Цикл": 2, "ATS-цикл": 4}
_cycle_started: dict[str, float] = {}

# Лимит карточек — на окно PARSE_INTERVAL_MINUTES, а не на цикл: долгий цикл
# не должен держать очередь. Отправка идёт и из 5-минутной задачи.
_send_lock = threading.Lock()
_window_start = 0.0
_window_sent = 0


def send_ready() -> int:
    global _window_start, _window_sent
    with _send_lock:
        now = time.monotonic()
        if now - _window_start >= config.PARSE_INTERVAL_MINUTES * 60:
            _window_start, _window_sent = now, 0
        left = config.MODERATION_MAX_PER_CYCLE - _window_sent
        if left <= 0:
            return 0
        _pull_returns()
        sent = send_new_vacancies_to_moderation(limit=left)
        _window_sent += sent
        return sent


def full_cycle(parsers=None, lock=_cycle_lock, name="Цикл") -> None:
    """Парсинг источников. Карточки уходят в чат после каждого источника,
    не дожидаясь конца цикла."""
    if not lock.acquire(blocking=False):
        logger.info("%s: предыдущий запуск ещё идёт — этот пропускаю", name)
        return
    _cycle_started[name] = time.monotonic()
    try:
        send_ready()  # то, что уже лежит в базе, — сразу
        stats = run_cycle(parsers=parsers, after_parser=send_ready)
        parsed = stats.get("parsed", 0)
        saved = stats.get("saved", 0)
        # При цикле раз в 15 минут сводка после каждого прогона — спам в чат алертов.
        # Шлём только аномалию; итоги за день приходят в daily_report.
        if parsed == 0:
            send_alert(f"Внимание: {name} вернул 0 вакансий")
        logger.info("%s: найдено %d, новых %d", name, parsed, saved)
    except Exception as e:
        logger.exception("Ошибка: %s", name)
        send_alert(f"Ошибка ({name}): {type(e).__name__}: {e}")
    finally:
        _cycle_started.pop(name, None)
        lock.release()


def watchdog() -> None:
    for name, started in list(_cycle_started.items()):
        hours = (time.monotonic() - started) / 3600
        if hours > CYCLE_TIMEOUT_HOURS.get(name, 2):
            logger.error("%s висит %.1f ч — перезапускаю процесс", name, hours)
            send_alert(f"{name} завис на {hours:.1f} ч, перезапускаю бота")
            logging.shutdown()
            os._exit(1)


def slow_cycle() -> None:
    """ATS-харвестеры обходят сотни компаний ~2 часа — отдельно и редко, чтобы не держать быстрый цикл."""
    full_cycle(parsers=SLOW_PARSERS, lock=_slow_cycle_lock, name="ATS-цикл")


def night_probe_cycle() -> None:
    """Ночной авто-харвест ATS-токенов по именам компаний из свежих вакансий."""
    try:
        from tools.ats_night_probe import run_night_probe
        found = run_night_probe(since_hours=24)
        total = sum(len(v) for v in found.values())
        if total:
            logger.info("Ночной probe: найдено %d новых ATS-токенов", total)
    except Exception:
        logger.exception("Ошибка ночного probe ATS-токенов")


def weekly_globalwork_cycle() -> None:
    """Еженедельный харвест ATS-токенов из globalwork.ai."""
    try:
        from tools.discover_ats_from_globalwork import run_discovery
        added = run_discovery()
        total = sum(len(v) for v in added.values())
        if total:
            logger.info("Globalwork discovery: найдено %d новых ATS-токенов", total)
    except Exception:
        logger.exception("Ошибка еженедельного globalwork discovery")


def _pull_returns() -> int:
    """Отметка «Вернуть» во вкладке «Забраковано ботом» → вакансия снова идёт в чат."""
    try:
        ids = pull_returns()
        returned = database.mark_returned(ids) if ids else 0
        if returned:
            logger.info("Вернул из таблицы в чат: %d", returned)
        return returned
    except Exception:
        logger.exception("Не удалось забрать возвраты из таблицы")
        return 0


def scheduled_publish_cycle() -> None:
    """Публикует вакансии у которых наступило scheduled_at и возвращает отложенные «Позже»."""
    try:
        send_ready()
    except Exception:
        logger.exception("Ошибка отправки карточек")
    try:
        resent = resend_due_snoozed()
        if resent:
            logger.info("Вернул в чат отложенных: %d", resent)
    except Exception:
        logger.exception("Ошибка возврата отложенных вакансий")
    try:
        published = publish_due_scheduled()
        if published:
            logger.info("Опубликовано запланированных вакансий: %d", published)
    except Exception:
        logger.exception("Ошибка публикации запланированных вакансий")


def main() -> None:
    database.init_db()
    # Курируемый список визовых спонсоров: матч даёт +2 к score и подсветку в карточке.
    scoring.enable_visa_lookup(database.is_visa_sponsor)

    # Фоновый планировщик — не блокирует основной поток
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")

    # Первый цикл через 60 секунд — даём время умереть старому экземпляру
    # чтобы не получить 403 от hh.ru при двух OAuth-запросах подряд с одного IP
    scheduler.add_job(
        full_cycle,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=60),
        id="first_cycle",
    )
    # Интервал из PARSE_INTERVAL_MINUTES: цель — увидеть вакансию и откликнуться
    # за минуты. max_instances=1 — если цикл дольше интервала, следующий пропускается.
    scheduler.add_job(
        full_cycle,
        "interval",
        minutes=config.PARSE_INTERVAL_MINUTES,
        id="main_cycle",
        max_instances=1,
    )
    scheduler.add_job(
        slow_cycle,
        "interval",
        hours=SLOW_CYCLE_HOURS,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=20),
        id="slow_cycle",
        max_instances=1,
    )
    scheduler.add_job(
        scheduled_publish_cycle,
        "interval",
        minutes=5,
        id="scheduled_publish",
        max_instances=1,
    )
    scheduler.add_job(watchdog, "interval", minutes=5, id="watchdog")
    # Дневная сводка парсеров за прошедший день
    scheduler.add_job(
        daily_report,
        "cron",
        hour=config.DAILY_REPORT_HOUR,
        minute=0,
        id="daily_report",
        max_instances=1,
    )
    # Ночной probe ATS-токенов по именам компаний за день (03:30 МСК)
    scheduler.add_job(
        night_probe_cycle,
        "cron",
        hour=3,
        minute=30,
        id="night_probe",
        max_instances=1,
    )
    # Еженедельный харвест ATS-токенов из globalwork (воскресенье 04:00 МСК)
    scheduler.add_job(
        weekly_globalwork_cycle,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="weekly_globalwork",
        max_instances=1,
    )
    # Проверка балансов OpenRouter / Railway (алерт при падении ниже порога)
    scheduler.add_job(
        check_balances,
        "interval",
        minutes=config.BALANCE_CHECK_INTERVAL_MINUTES,
        id="balance_check",
        max_instances=1,
    )
    # Ежедневная денежная сводка: остаток + траты
    scheduler.add_job(
        money_report,
        "cron",
        hour=config.DAILY_REPORT_HOUR,
        minute=5,
        id="money_report",
        max_instances=1,
    )
    # Разовая сводка за вчера сегодня в 15:00 МСК (исключение, удалить после)
    _oneshot = datetime(2026, 6, 9, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    if _oneshot > datetime.now(ZoneInfo("Europe/Moscow")):
        scheduler.add_job(
            daily_report,
            "date",
            run_date=_oneshot,
            id="daily_report_oneshot",
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            money_report,
            "date",
            run_date=_oneshot,
            id="money_report_oneshot",
            misfire_grace_time=3600,
        )
    scheduler.start()
    logger.info("Планировщик запущен: цикл каждые %d мин", config.PARSE_INTERVAL_MINUTES)

    async def on_error(update, context) -> None:
        if isinstance(context.error, Conflict):
            logger.error("Конфликт: запущен другой экземпляр бота. Завершаем процесс.")
            scheduler.shutdown(wait=False)
            logging.shutdown()
            # os._exit вместо sys.exit: внутри async error-handler PTB
            # SystemExit перехватывается event-loop'ом и процесс гаснет с кодом 0
            # (Railway видит "Completed" и не рестартит). os._exit даёт реальный
            # код 1 → срабатывает restartPolicyType=ON_FAILURE.
            os._exit(1)
        logger.exception("Необработанная ошибка бота", exc_info=context.error)

    # Telegram-бот стартует сразу — не ждёт окончания первого цикла
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CallbackQueryHandler(handle_moderation))

    def _chat_filter(chat_id_str: str):
        if not chat_id_str:
            return None
        return (
            filters.Chat(int(chat_id_str)) if chat_id_str.lstrip("-").isdigit()
            else filters.Chat(username=chat_id_str.lstrip("@"))
        )

    ru_filter = _chat_filter(config.TELEGRAM_MODERATION_CHAT_RU)
    gl_filter = _chat_filter(config.TELEGRAM_MODERATION_CHAT_GLOBAL)
    if ru_filter and gl_filter and config.TELEGRAM_MODERATION_CHAT_RU != config.TELEGRAM_MODERATION_CHAT_GLOBAL:
        mod_filter = ru_filter | gl_filter
    elif ru_filter:
        mod_filter = ru_filter
    elif gl_filter:
        mod_filter = gl_filter
    else:
        mod_filter = filters.Chat([])

    app.add_handler(MessageHandler(
        filters.TEXT & filters.REPLY & mod_filter,
        handle_edit_reply,
    ))
    logger.info("Бот запущен, слушаем кнопки модерации...")
    app.run_polling(
        allowed_updates=["callback_query", "message"],
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
