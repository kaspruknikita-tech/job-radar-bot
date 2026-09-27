"""
Парсер вакансий из Telegram-каналов через Telethon.

Требует переменных окружения:
  TG_API_ID           — числовой ID приложения (my.telegram.org)
  TG_API_HASH         — хэш приложения
  TG_SESSION_STRING   — строка сессии (получается через scripts/gen_tg_session.py)
  TG_SOURCE_CHANNELS  — каналы-источники через запятую (напр. @researchjobs,@uxjobs)
  TG_DAYS_BACK        — за сколько дней брать сообщения (по умолчанию 7)
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import config
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    _TELETHON_AVAILABLE = True
except ImportError:
    _TELETHON_AVAILABLE = False
    logger.warning("[telegram] Telethon не установлен — парсер отключён")

# Паттерны для определения формата работы
_REMOTE_RE = re.compile(r"удалён|remote|дистанц", re.I)
_HYBRID_RE = re.compile(r"гибрид|hybrid", re.I)
_OFFICE_RE = re.compile(r"\bофис\b|on[\s-]?site", re.I)

# Паттерн для зарплаты: "150 000 — 250 000 руб" / "$3000–5000"
_SALARY_RE = re.compile(
    r"(\d[\d\s]{2,})\s*[-—–]\s*(\d[\d\s]{2,})\s*(руб|₽|usd|\$|eur|€)",
    re.I,
)
_CURRENCY_MAP = {
    "руб": "RUR", "₽": "RUR",
    "usd": "USD", "$": "USD",
    "eur": "EUR", "€": "EUR",
}


def _parse_salary(text: str) -> tuple[int | None, int | None, str | None]:
    m = _SALARY_RE.search(text)
    if not m:
        return None, None, None
    try:
        sal_min = int(m.group(1).replace(" ", ""))
        sal_max = int(m.group(2).replace(" ", ""))
        currency = _CURRENCY_MAP.get(m.group(3).lower())
        return sal_min, sal_max, currency
    except (ValueError, AttributeError):
        return None, None, None


def _detect_work_format(text: str) -> str | None:
    if _REMOTE_RE.search(text):
        return "Удалёнка"
    if _HYBRID_RE.search(text):
        return "Гибрид"
    if _OFFICE_RE.search(text):
        return "Офис"
    return None


def vacancy_title(text: str, max_len: int = 120) -> str:
    """Заголовок поста. Первая строка в каналах почти всегда хэштеги и эмодзи, и фильтр
    по заголовку резал бы годные посты. Берём среди первых строк ту, где есть должность
    из белого списка, иначе первую строку с текстом."""
    from filters.stopwords import _WHITELIST_RE

    lines = []
    for raw in text.splitlines():
        line = re.sub(r"#\S+", " ", raw)
        line = re.sub(r"[^\w\s\-–—()/.,:+&«»\"'!?$€₽%]", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" -–—:|.,")
        if len(re.findall(r"[A-Za-zА-Яа-яЁё]", line)) >= 3:
            lines.append(line)
        if len(lines) >= 6:
            break
    for line in lines:
        if _WHITELIST_RE.search(line):
            return line[:max_len]
    return (lines[0] if lines else text.strip())[:max_len]


class TelegramChannelParser(BaseParser):
    source_name = "telegram"
    channel = "ru"

    def fetch(self) -> list[dict]:
        if not _TELETHON_AVAILABLE:
            return []

        if not all([config.TG_API_ID, config.TG_API_HASH,
                    config.TG_SESSION_STRING, config.TG_SOURCE_CHANNELS]):
            logger.warning(
                "[telegram] Не заданы TG_API_ID / TG_API_HASH / "
                "TG_SESSION_STRING / TG_SOURCE_CHANNELS — пропускаем"
            )
            return []

        return asyncio.run(self._fetch_all())

    async def _fetch_all(self) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=config.TG_DAYS_BACK)
        result = []

        async with TelegramClient(
            StringSession(config.TG_SESSION_STRING),
            config.TG_API_ID,
            config.TG_API_HASH,
        ) as client:
            for channel_ref in config.TG_SOURCE_CHANNELS:
                channel_ref = channel_ref.strip()
                if not channel_ref:
                    continue
                try:
                    msgs = await self._fetch_channel(client, channel_ref, since)
                    result.extend(msgs)
                    logger.info("[telegram] %s: получено %d сообщений", channel_ref, len(msgs))
                except Exception:
                    logger.exception("[telegram] Ошибка при чтении канала %s", channel_ref)

        return result

    async def _fetch_channel(self, client, channel_ref: str, since: datetime) -> list[dict]:
        vacancies = []
        async for message in client.iter_messages(channel_ref, limit=200):
            if not message.date or not message.text:
                continue

            msg_date = message.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)

            # iter_messages идёт от новых к старым — как только вышли за окно, стоп
            if msg_date < since:
                break

            text = message.text
            sal_min, sal_max, currency = _parse_salary(text)
            channel_username = channel_ref.lstrip("@")

            vacancies.append({
                "external_id": f"{channel_username}_{message.id}",
                "title": vacancy_title(text),
                "company": "",
                "salary_min": sal_min,
                "salary_max": sal_max,
                "currency": currency,
                "location": None,
                "work_format": _detect_work_format(text),
                "url": f"https://t.me/{channel_username}/{message.id}",
                "description": text,
                "published_at": msg_date.isoformat(),
            })

        return vacancies
