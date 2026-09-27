"""
Обработчики Telegram-бота.
handle_moderation — реагирует на нажатия кнопок в чате модерации.
handle_edit_reply — обрабатывает текстовый ответ с новым описанием вакансии.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, filters

import config
import database
from bot.alerts import send_alert
from bot.templates import format_ru, format_global
from exporters.sheets import update_decision

logger = logging.getLogger(__name__)

_EDIT_PROMPT_PREFIX = "✏️ Вакансия #"


def _is_authorized_chat(message) -> bool:
    """Принимает чат как численный id, так и @username — env может содержать любой формат."""
    chat = message.chat
    candidates = {str(chat.id)}
    if chat.username:
        candidates.add(f"@{chat.username}")
        candidates.add(chat.username)
    allowed = {
        c for c in (config.TELEGRAM_MODERATION_CHAT_RU, config.TELEGRAM_MODERATION_CHAT_GLOBAL)
        if c
    }
    return bool(candidates & allowed)


def _get_channel_id(channel: str) -> str:
    return config.TELEGRAM_CHANNEL_RU if channel == "ru" else config.TELEGRAM_CHANNEL_GLOBAL


def _format(vacancy: dict) -> str:
    return format_ru(vacancy) if vacancy.get("channel") == "ru" else format_global(vacancy)


def _markup(keyboard: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"]) for btn in row]
        for row in keyboard["inline_keyboard"]
    ])


async def _record_decision(vacancy: dict, decision: str, reason: str) -> None:
    """Решение → Google-таблица. Сеть в отдельном потоке: бот не должен подвисать
    и падать, если таблица недоступна — решение уже сохранено в БД."""
    from bot.moderator import _get_or_score
    try:
        scoring = _get_or_score(vacancy)
        await asyncio.to_thread(update_decision, vacancy, scoring.model_dump() if scoring else {}, decision, reason)
    except Exception:
        logger.exception("Не удалось записать решение по вакансии id=%s в таблицу", vacancy.get("id"))


async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия кнопок модерации."""
    query = update.callback_query

    # Только из авторизованных чатов модерации (id или @username)
    if not _is_authorized_chat(query.message):
        try:
            await query.answer("Unauthorized", show_alert=True)
        except Exception:
            pass
        return

    # answer() имеет 10-минутный TTL — молча игнорируем если устарел
    try:
        await query.answer()
    except Exception:
        pass

    parts = query.data.split(":")
    if len(parts) < 2:
        return
    action = parts[0]
    try:
        vacancy_id = int(parts[1])
        if not (0 < vacancy_id < 2**31):
            return
    except (ValueError, IndexError):
        return

    actor = (query.from_user.first_name or "модератор").replace("\n", " ").replace("\r", " ")

    vacancy = database.get_vacancy_by_id(vacancy_id)
    if not vacancy:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if action == "apply":
        database.mark_decision(vacancy_id, "applied")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Откликаюсь — записал в таблицу")
        logger.info("Решение: откликаюсь id=%s", vacancy_id)
        await _record_decision(vacancy, "Откликаюсь", "")
        return

    if action == "decline":
        from bot.moderator import _decline_keyboard
        await query.edit_message_reply_markup(reply_markup=_markup(_decline_keyboard(vacancy_id)))
        return

    if action == "back":
        from bot.moderator import _keyboard
        await query.edit_message_reply_markup(reply_markup=_markup(_keyboard(vacancy_id)))
        return

    if action == "reason":
        from bot.moderator import DECLINE_REASONS
        label = DECLINE_REASONS.get(parts[2] if len(parts) > 2 else "", "другое")
        database.mark_decision(vacancy_id, "declined", label)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ Не подходит: {label}")
        logger.info("Решение: не подходит id=%s причина=%s", vacancy_id, label)
        await _record_decision(vacancy, "Не подходит", label)
        return

    if action == "later":
        try:
            minutes = int(parts[2])
        except (ValueError, IndexError):
            return
        if minutes not in {180, 1440}:
            return
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        database.mark_snoozed(vacancy_id, until)
        await query.edit_message_reply_markup(reply_markup=None)
        msk = until + timedelta(hours=3)
        await query.message.reply_text(f"⏳ Верну в чат {msk.strftime('%d.%m %H:%M')} МСК")
        logger.info("Отложена вакансия id=%s до %s", vacancy_id, until)
        return

    if action == "approve":
        channel_id = _get_channel_id(vacancy["channel"])
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text=_format(vacancy),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            database.mark_posted(vacancy_id)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Опубликовано — {actor}")
            logger.info("Опубликована вакансия id=%s (%s)", vacancy_id, actor)
        except Exception:
            logger.exception("Ошибка публикации вакансии id=%s", vacancy_id)
            send_alert(f"Не удалось опубликовать вакансию id={vacancy_id}")
            await query.answer("Ошибка при публикации — проверь логи", show_alert=True)

    elif action == "reject":
        database.mark_rejected(vacancy_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ Отклонено — {actor}")
        logger.info("Отклонена вакансия id=%s (%s)", vacancy_id, actor)

    elif action == "edit":
        # selective=True не сработает: ForceReply таргетирует автора reply_to_message,
        # а это сам бот. Без selective клавиатура ответа открывается у всех в чате.
        await query.message.reply_text(
            f"{_EDIT_PROMPT_PREFIX}{vacancy_id} — пришли новое описание:",
            reply_markup=ForceReply(),
        )

    elif action == "schedule":
        try:
            minutes = int(parts[2])
            if minutes not in {30, 60, 180, 360, 720, 1080, 1440}:
                return
        except (ValueError, IndexError):
            return
        publish_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        database.mark_scheduled(vacancy_id, publish_at)
        await query.edit_message_reply_markup(reply_markup=None)
        msk = publish_at + timedelta(hours=3)
        await query.message.reply_text(
            f"⏰ Запланировано на {msk.strftime('%d.%m %H:%M')} МСК — {actor}"
        )
        logger.info("Запланирована вакансия id=%s на %s (%s)", vacancy_id, publish_at, actor)


async def handle_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ответ на запрос редактирования описания."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    prompt_text = msg.reply_to_message.text or ""
    if not prompt_text.startswith(_EDIT_PROMPT_PREFIX):
        return

    logger.info("handle_edit_reply сработал: chat=%s user=%s", msg.chat_id, msg.from_user.id if msg.from_user else None)

    try:
        # Извлекаем vacancy_id из текста "✏️ Вакансия #123 — пришли новое описание:"
        id_part = prompt_text[len(_EDIT_PROMPT_PREFIX):].split(" ")[0]
        vacancy_id = int(id_part)
    except (ValueError, IndexError):
        logger.warning("Не удалось распарсить vacancy_id из prompt: %r", prompt_text[:100])
        return

    new_description = msg.text or ""
    if len(new_description) < 10:
        await msg.reply_text("Слишком короткое описание, попробуй ещё раз.")
        return

    try:
        database.update_vacancy_description(vacancy_id, new_description)
    except Exception:
        logger.exception("Ошибка обновления описания вакансии id=%s в БД", vacancy_id)
        await msg.reply_text(f"❌ Не удалось сохранить описание #{vacancy_id}. Смотри логи.")
        return

    # Перерисовываем оригинальное сообщение в чате модерации; если карточки нет — шлём новую.
    vacancy = database.get_vacancy_by_id(vacancy_id)
    if not vacancy:
        await msg.reply_text(f"✅ Описание #{vacancy_id} сохранено, но вакансия не найдена для перерисовки.")
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from bot.moderator import _format, _get_moderation_chat, _get_or_score, _keyboard, _scoring_footer

    scoring_result = _get_or_score(vacancy)
    new_text = _format(vacancy, scoring_result)
    if scoring_result:
        new_text += _scoring_footer(scoring_result, vacancy)
    mod_chat = _get_moderation_chat(vacancy.get("channel", ""))
    kbd_dict = _keyboard(vacancy_id, vacancy["channel"])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"]) for btn in row]
        for row in kbd_dict["inline_keyboard"]
    ])

    mod_msg_id = vacancy.get("moderation_message_id")
    redraw_failed = False

    if mod_msg_id:
        logger.info("edit_message_text: chat=%s msg_id=%s text_len=%s", mod_chat, mod_msg_id, len(new_text))
        try:
            await context.bot.edit_message_text(
                chat_id=mod_chat,
                message_id=mod_msg_id,
                text=new_text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            logger.info("edit_message_text OK для вакансии id=%s", vacancy_id)
        except Exception as e:
            logger.warning("Не удалось обновить сообщение модерации id=%s: %s", vacancy_id, e, exc_info=True)
            redraw_failed = True
    else:
        logger.warning("moderation_message_id отсутствует для вакансии id=%s, шлём новую карточку", vacancy_id)
        redraw_failed = True

    if redraw_failed:
        # Шлём новую карточку — модератор должен видеть результат.
        try:
            sent = await context.bot.send_message(
                chat_id=mod_chat,
                text=new_text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            try:
                database.save_moderation_message_id(vacancy_id, sent.message_id)
            except Exception:
                logger.warning("save_moderation_message_id не сработал для id=%s", vacancy_id, exc_info=True)
        except Exception:
            logger.exception("Не удалось отправить обновлённую карточку id=%s", vacancy_id)
            await msg.reply_text(f"⚠️ Описание #{vacancy_id} сохранено в БД, но карточка не обновилась. Смотри логи.")
            return

    await msg.reply_text(f"✅ Описание вакансии #{vacancy_id} обновлено.")
    logger.info("Обновлено описание вакансии id=%s", vacancy_id)
