"""
Парсер rabota.ru.

Публичного API нет, состояние Nuxt завёрнуто в функцию — поэтому идём по SSR:
листинг /vacancy/?query=<маска> отдаёт ссылки /vacancy/<id>, детальная —
h1, блок [itemprop=description] и текст зарплаты.

JSON-LD у источника нет, зарплату разбираем из строки вида «30 000 — 75 000 руб.».
"""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

import config
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

BASE = "https://www.rabota.ru"
LIST_URL = f"{BASE}/vacancy/"
REQUEST_DELAY = 0.5
REQUEST_TIMEOUT = 25

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

SEARCH_QUERIES = P.SEARCH_RABOTARU  # правится в profile/profile.py

_VACANCY_HREF_RE = re.compile(r"/vacancy/(\d+)")
_DIGITS_RE = re.compile(r"\d[\d\s ]*")


def _parse_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """«30 000 — 75 000 руб.» → (30000, 75000, 'RUR'). Одно число — это минимум."""
    if not text:
        return None, None, None
    nums = []
    for m in _DIGITS_RE.finditer(text):
        raw = m.group(0).replace(" ", "").replace(" ", "")
        if raw.isdigit() and len(raw) >= 4:
            nums.append(int(raw))
    if not nums:
        return None, None, None
    currency = "RUR" if ("руб" in text or "₽" in text) else None
    if len(nums) == 1:
        return nums[0], None, currency
    return nums[0], nums[1], currency


class RabotaRuParser(BaseParser):
    source_name = "rabota.ru"
    channel = "ru"

    def fetch(self) -> list[dict]:
        urls: dict[str, str] = {}
        for query in SEARCH_QUERIES:
            for vid, url in self._list(query).items():
                urls.setdefault(vid, url)

        logger.info("[rabota.ru] Ссылок в листингах: %d", len(urls))

        fresh = [(vid, url) for vid, url in urls.items() if not self.is_known(vid)]
        out: list[dict] = []
        for vid, url in fresh[:config.RABOTARU_MAX_VACANCIES]:
            v = self._detail(vid, url)
            # Фильтр — в планировщике: отклонённые сохранятся, и is_known их запомнит.
            if v:
                out.append(v)
        logger.info("[rabota.ru] Новых карточек: %d", len(out))
        return out

    def _list(self, query: str) -> dict[str, str]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(LIST_URL, headers=_HEADERS, params={"query": query},
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("[rabota.ru] Ошибка листинга query=%r", query)
            return {}
        return {m.group(1): f"{BASE}/vacancy/{m.group(1)}/"
                for m in _VACANCY_HREF_RE.finditer(resp.text)}

    def _detail(self, vid: str, url: str) -> dict | None:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.debug("[rabota.ru] не открылась %s", url)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.select_one("h1")
        if not h1:
            return None
        title = h1.get_text(strip=True)

        description_el = soup.select_one("[itemprop=description]")
        salary_el = soup.select_one("[class*=salary]")
        smin, smax, currency = _parse_salary(salary_el.get_text(" ", strip=True) if salary_el else "")

        company = ""
        for a in soup.select('a[href*="/company/"]'):
            text = a.get_text(strip=True)
            # Первая ссылка часто рекламная («Работа в Сбере») — берём следующую.
            if text and not text.startswith("Работа в"):
                company = text
                break

        return {
            "external_id": vid,
            "title": title,
            "company": company,
            "salary_min": smin,
            "salary_max": smax,
            "currency": currency,
            "location": "",
            "work_format": None,
            "url": url,
            "description": str(description_el) if description_el else "",
            "published_at": None,
        }
