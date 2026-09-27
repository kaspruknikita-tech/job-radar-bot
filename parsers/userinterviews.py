"""
Парсер userinterviews.com/ux-job-board.
Курируемая доска UX research-вакансий. Карточки в Webflow CMS, SSR.
Поля: title, company, location, work_format, url (внешний ATS).
Salary/description на листинге нет, детальной страницы нет.
"""

import logging

import requests
from bs4 import BeautifulSoup

from parsers.base import BaseParser
from tools.ats_harvest import harvest_ats_tokens

logger = logging.getLogger(__name__)

URL = "https://www.userinterviews.com/ux-job-board"
TIMEOUT = 20

WHITELIST = [
    "researcher", "research", "ux", "cx", "usability",
    "service designer", "voice of customer", "ux strategist",
    "research ops", "customer experience", "insight",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_WORK_FORMAT_MAP = {
    "on site": "Onsite",
    "onsite": "Onsite",
    "on-site": "Onsite",
    "hybrid": "Hybrid",
    "remote": "Remote",
}


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _text(el) -> str:
    return el.get_text(strip=True) if el else ""


def _get_apply_url(card) -> str:
    link = card.select_one("a.jb-link-block")
    return link.get("href", "").strip() if link else ""


def _parse_card(card) -> dict | None:
    apply_url = _get_apply_url(card)
    if not apply_url:
        return None

    title = _text(card.select_one('[fs-cmsfilter-field="title"]'))
    if not title:
        return None

    company = _text(card.select_one('.div-block-145 [fs-cmsfilter-field="company"]'))
    location = _text(card.select_one('.div-block-145 [fs-cmsfilter-field="location"]'))

    wf_el = card.select_one('.jb-text-wrap [fs-cmsfilter-field="work-mode"]')
    wf_raw = _text(wf_el).lower()
    work_format = _WORK_FORMAT_MAP.get(wf_raw)

    return {
        "external_id": "",
        "title": title,
        "company": company,
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "location": location,
        "work_format": work_format,
        "url": apply_url,
        "description": "",
    }


class UserInterviewsParser(BaseParser):
    source_name = "userinterviews"
    channel = "global"
    harvest_ats = False  # свой ручной харвест по всем карточкам (см. fetch)

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(URL, headers=_HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("[userinterviews] Ошибка загрузки листинга")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.job-board-item.w-dyn-item")
        logger.info("[userinterviews] Карточек на странице: %d", len(cards))

        result: list[dict] = []
        seen_urls: set[str] = set()
        for card in cards:
            parsed = _parse_card(card)
            if not parsed:
                continue
            if parsed["url"] in seen_urls:
                continue
            seen_urls.add(parsed["url"])
            if not _is_relevant(parsed["title"]):
                continue
            result.append(parsed)

        logger.info("[userinterviews] Итого после whitelist: %d", len(result))

        # Авто-харвест ATS-токенов из всех собранных URL (greenhouse/ashby/lever).
        # Берём со всех карточек, не только прошедших whitelist — токен компании
        # один на все её вакансии, и роли в её COMPANIES уже фильтрует ATS-парсер.
        try:
            urls = [u for u in (_get_apply_url(c) for c in cards) if u]
            harvest_ats_tokens(urls, source_label="userinterviews")
        except Exception:
            logger.exception("[userinterviews] Сбой авто-харвеста ATS, продолжаем")

        return result
