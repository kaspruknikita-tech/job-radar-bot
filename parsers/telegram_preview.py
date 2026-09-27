"""
Telegram-каналы без логина: публичные веб-превью https://t.me/s/<канал>.

Так читали каналы jospars/job_hunter и скан jobscan.py: ключи и сессия не нужны.
Каналы с закрытым превью (Telegram отвечает редиректом) так не прочитать — для них нужен
Telethon (parsers/telegram.py) с TG_API_ID / TG_API_HASH / TG_SESSION_STRING. Когда эти ключи
заданы, превью выключается: Telethon сам читает все каналы.

Источник и id поста совпадают с Telethon-парсером (telegram, <канал>_<номер>) —
при переключении один пост не придёт дважды.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

import config
from parsers.base import BaseParser
from parsers.telegram import _detect_work_format, _parse_salary, vacancy_title

logger = logging.getLogger(__name__)

PREVIEW_URL = "https://t.me/s/{channel}"
REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 20
MIN_POST_LENGTH = 80  # короче — объявление, опрос или репост без текста

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_POST_RE = re.compile(r"^([A-Za-z0-9_]+)/(\d+)$")
# Резюме и «ищу работу» — не вакансии
_RESUME_RE = re.compile(r"#резюме|#resume|#cv\b|#ищуработу|ищу работу|в поиске работы", re.I)


def parse_page(html: str) -> list[dict]:
    """Посты со страницы превью: [{id, date, text, html}] в порядке страницы (от старых к новым)."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for wrap in soup.find_all("div", class_="tgme_widget_message_wrap"):
        message = wrap.find("div", class_="tgme_widget_message")
        match = _POST_RE.match((message.get("data-post") if message else "") or "")
        body = wrap.find("div", class_="tgme_widget_message_text")
        time_tag = wrap.find("time")
        if not (match and body and time_tag and time_tag.get("datetime")):
            continue
        try:
            published = datetime.fromisoformat(time_tag["datetime"])
        except ValueError:
            continue
        html_body = str(body)
        for br in body.find_all("br"):
            br.replace_with("\n")
        posts.append({
            "id": int(match.group(2)),
            "date": published if published.tzinfo else published.replace(tzinfo=timezone.utc),
            "text": body.get_text().strip(),
            "html": html_body,
        })
    return posts


class TelegramPreviewParser(BaseParser):
    source_name = "telegram"
    channel = "ru"
    harvest_ats = False  # ссылки t.me — не ATS-борды

    def fetch(self) -> list[dict]:
        if config.TG_API_ID and config.TG_API_HASH and config.TG_SESSION_STRING:
            logger.info("[telegram] ключи Telethon заданы — превью не используется")
            return []
        if not config.TG_SOURCE_CHANNELS:
            return []

        since = datetime.now(timezone.utc) - timedelta(days=config.TG_DAYS_BACK)
        vacancies, readable, closed = [], 0, []
        for ref in config.TG_SOURCE_CHANNELS:
            channel = ref.strip().lstrip("@")
            if not channel:
                continue
            posts = self._channel(channel, since)
            if posts is None:
                closed.append(channel)
                continue
            readable += 1
            vacancies.extend(posts)
        logger.info("[telegram] превью: каналов читается %d, закрыто %d, постов-вакансий %d",
                    readable, len(closed), len(vacancies))
        if closed:
            logger.debug("[telegram] закрытое превью: %s", ", ".join(closed))
        return vacancies

    def _channel(self, channel: str, since: datetime) -> list[dict] | None:
        """Посты канала свежее since. None — превью закрыто или канал пуст."""
        before, result = None, []
        for page in range(config.TG_PREVIEW_MAX_PAGES):
            try:
                time.sleep(REQUEST_DELAY)
                resp = requests.get(PREVIEW_URL.format(channel=channel), headers=_HEADERS,
                                    params={"before": before} if before else None,
                                    timeout=REQUEST_TIMEOUT, allow_redirects=False)
            except requests.RequestException:
                logger.warning("[telegram] %s: сетевая ошибка", channel)
                return result
            posts = parse_page(resp.text) if resp.status_code == 200 else []
            if not posts:
                return None if page == 0 else result
            reached_old = False
            for post in posts:
                if post["date"] < since:
                    reached_old = True
                    continue
                vacancy = self._to_vacancy(channel, post)
                if vacancy:
                    result.append(vacancy)
            if reached_old:
                break
            before = min(p["id"] for p in posts)
        return result

    @staticmethod
    def _to_vacancy(channel: str, post: dict) -> dict | None:
        text = post["text"]
        if len(text) < MIN_POST_LENGTH or _RESUME_RE.search(text):
            return None
        salary_min, salary_max, currency = _parse_salary(text)
        return {
            "external_id": f"{channel}_{post['id']}",
            "title": vacancy_title(text),
            "company": "",
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": currency,
            "location": None,
            "work_format": _detect_work_format(text),
            "url": f"https://t.me/{channel}/{post['id']}",
            "description": post["html"],
            "published_at": post["date"].isoformat(),
        }
