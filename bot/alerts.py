"""
Алерты в Telegram-группу мониторинга.
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

import config
import database
from bot.tg_api import call as tg_call

logger = logging.getLogger(__name__)

ALERT_MENTION = config.TELEGRAM_ALERT_MENTION
REPORT_MENTION = config.TELEGRAM_REPORT_MENTION

MSK = ZoneInfo("Europe/Moscow")

_MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def send_alert(text: str, parse_mode: str | None = None) -> None:
    if not config.TELEGRAM_ALERT_CHAT or not config.TELEGRAM_BOT_TOKEN:
        return
    kwargs = {"chat_id": config.TELEGRAM_ALERT_CHAT, "text": text}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    try:
        tg_call("sendMessage", **kwargs)
    except Exception:
        logger.exception("Не удалось отправить алерт")


def _railway_status() -> dict | None:
    """Возвращает {remaining} в USD или None."""
    if not config.RAILWAY_API_TOKEN:
        return None
    try:
        query = "{ me { creditBalance } }"
        resp = requests.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": query},
            headers={
                "Authorization": f"Bearer {config.RAILWAY_API_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            logger.warning("Railway API errors: %s", errors)
            return None
        balance_cents = payload.get("data", {}).get("me", {}).get("creditBalance")
        if balance_cents is None:
            logger.warning("Railway: creditBalance не найден в ответе: %s", payload)
            return None
        # Railway возвращает баланс в центах
        return {"remaining": balance_cents / 100.0}
    except Exception:
        logger.exception("Не удалось получить баланс Railway")
        return None


def check_balances() -> None:
    """Шлёт алерт только если баланс ниже порога."""
    r = _railway_status()
    if r and r["remaining"] < config.RAILWAY_BALANCE_THRESHOLD:
        send_alert(
            f"[RAILWAY] Баланс заканчивается!\n"
            f"Осталось: ${r['remaining']:.2f} (порог: ${config.RAILWAY_BALANCE_THRESHOLD})\n"
            f"{ALERT_MENTION}"
        )


def money_report() -> None:
    """Ежедневная денежная сводка: остаток Railway. Нет данных — не шлём пустое сообщение."""
    r = _railway_status()
    if r is None:
        logger.info("Денежная сводка: платных сервисов нет, сообщение не отправляется")
        return

    lines = ["💰 <b>Баланс сервисов</b>", ""]
    if r is not None:
        lines.append(f"<b>Railway:</b> осталось ${r['remaining']:.2f}")
    else:
        lines.append("<b>Railway:</b> нет данных")

    if REPORT_MENTION:
        lines.append("")
        lines.append(REPORT_MENTION)
    send_alert("\n".join(lines), parse_mode="HTML")


# --- Дневная сводка парсеров ---

def _per_cycle(value: int, cycles: int) -> float:
    return value / cycles if cycles else 0.0


def _fmt_delta(curr: float, prev: float) -> str:
    """Стрелка + процент изменения. Сравнивает нормализованные на цикл значения."""
    if prev == 0:
        return "🆕" if curr > 0 else "="
    pct = (curr - prev) / prev * 100
    if abs(pct) < 1:
        return "="
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow}{pct:+.0f}%"


def _short(name: str, width: int = 10) -> str:
    return name[:width].ljust(width)


def _build_report(report_day, cur: dict, prev: dict, ats: dict | None = None) -> str:
    date_str = f"{report_day.day} {_MONTHS_RU[report_day.month - 1]}"
    cyc, prev_cyc = cur["cycles"], prev["cycles"]

    # Таблица по источникам (моноширинный блок). Молчащие парсеры — отдельной строкой.
    header = f"{_short('Источник')} {'Сырьё':>6} {'Прош':>5} {'Отсев':>5}"
    sep = "─" * len(header)
    lines = [header, sep]
    silent = []
    for src, s in cur["by_source"].items():
        if s["parsed"] == 0:
            silent.append(src)
            continue
        lines.append(
            f"{_short(src)} {s['parsed']:>6} {s['passed']:>5} {s['rejected']:>5}"
        )
    t = cur["totals"]
    lines.append(sep)
    lines.append(f"{_short('ИТОГО')} {t['parsed']:>6} {t['passed']:>5} {t['rejected']:>5}")
    table = "<pre>" + "\n".join(lines) + "</pre>"

    pt = prev["totals"]

    def block(label: str, key: str) -> str:
        per = _per_cycle(t[key], cyc)
        delta = _fmt_delta(per, _per_cycle(pt[key], prev_cyc))
        return f"{label} <b>{t[key]}</b>  ({per:.1f}/цикл, {delta})"

    silent_line = f"\n⚠️ Молчат: {', '.join(silent)}\n" if silent else ""

    ats = ats or {"url": 0, "night": 0}
    ats_total = ats.get("url", 0) + ats.get("night", 0)
    ats_line = (
        f"🔑 Новых ATS-токенов: <b>{ats_total}</b> "
        f"(по ссылкам {ats.get('url', 0)}, ночной probe {ats.get('night', 0)})\n"
    )

    msg = (
        f"📊 <b>Сводка парсеров за {date_str}</b>\n"
        f"Циклов: {cyc} (днём ранее {prev_cyc})\n\n"
        f"{table}\n"
        f"{block('✅ Прошли фильтры:', 'passed')}\n"
        f"{block('❌ Отсев списками:', 'rejected')}\n"
        f"{block('🔁 Дубликаты:', 'duplicates')}\n"
        f"{block('📥 Сырья всего:', 'parsed')}\n"
        f"{ats_line}"
        f"{silent_line}\n"
        f"<i>Δ — изменение к днём ранее, нормировано на 1 цикл шедулера.</i>\n"
        f"{REPORT_MENTION}"
    )
    return msg


def daily_report() -> None:
    """Шлёт в чат мониторинга сводку парсеров за прошедший день."""
    now = datetime.now(MSK)
    report_day = (now - timedelta(days=1)).date()
    day_start = datetime.combine(report_day, time.min, tzinfo=MSK)
    day_end = day_start + timedelta(days=1)
    prev_start = day_start - timedelta(days=1)

    try:
        cur = database.get_parser_stats(day_start, day_end)
        prev = database.get_parser_stats(prev_start, day_start)
    except Exception:
        logger.exception("daily_report: не удалось получить статистику")
        return

    try:
        ats = database.get_discovered_counts(day_start, day_end)
    except Exception:
        logger.exception("daily_report: не удалось получить статистику ATS-токенов")
        ats = None

    date_str = f"{report_day.day} {_MONTHS_RU[report_day.month - 1]}"
    if cur["cycles"] == 0:
        send_alert(f"📊 Сводка за {date_str}: циклов не было (воркер простаивал?).\n{REPORT_MENTION}")
        return

    send_alert(_build_report(report_day, cur, prev, ats), parse_mode="HTML")
