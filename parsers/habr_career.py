"""
Парсер career.habr.com.

Список — публичный JSON: GET /api/frontend/vacancies?q=...&page=N&type=all
(ключа не требует, 25 вакансий на страницу, есть зарплата и remoteWork).
Описания в списке нет, а скорингу оно нужно — дотягиваем HTML детальной
страницы и берём блок .vacancy-description__text.

Фильтр по специализации (spec=) эндпоинт игнорирует, поэтому ищем запросами.
"""

import logging
import time

import requests
from bs4 import BeautifulSoup

import config
from filters.stopwords import apply_filters
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

BASE = "https://career.habr.com"
API_URL = f"{BASE}/api/frontend/vacancies"
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20
DESCRIPTION_SELECTOR = ".vacancy-description__text"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SEARCH_QUERIES = P.SEARCH_HABR_CAREER  # правится в profile/profile.py

_CURRENCY_MAP = {"rur": "RUR", "rub": "RUR", "usd": "USD", "eur": "EUR"}


class HabrCareerParser(BaseParser):
    source_name = "habr_career"
    channel = "ru"

    def fetch(self) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()

        for query in SEARCH_QUERIES:
            for page in range(1, config.HABR_MAX_PAGES + 1):
                items = self._search(query, page)
                if not items:
                    break
                for item in items:
                    vid = str(item.get("id", ""))
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    v = self._parse(item)
                    if v:
                        out.append(v)

        # Детальные страницы дороги — тянем их только для прошедших белый список.
        relevant = [v for v in out if apply_filters(v) and not self.is_known(v["external_id"])]
        for v in relevant:
            v["description"] = self._fetch_description(v["url"]) or v["description"]

        logger.info("[habr_career] В листингах %d, релевантных %d", len(out), len(relevant))
        return relevant

    def _search(self, query: str, page: int) -> list[dict]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(
                API_URL, headers=_HEADERS,
                params={"q": query, "page": page, "type": "all"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("list") or []
        except (requests.RequestException, ValueError):
            logger.warning("[habr_career] Ошибка поиска q=%r стр=%d", query, page)
            return []

    def _fetch_description(self, url: str) -> str:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers={"User-Agent": _HEADERS["User-Agent"]},
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.debug("[habr_career] не открылась детальная %s", url)
            return ""
        el = BeautifulSoup(resp.text, "html.parser").select_one(DESCRIPTION_SELECTOR)
        return str(el) if el else ""

    @staticmethod
    def _parse(item: dict) -> dict | None:
        title = (item.get("title") or "").strip()
        href = item.get("href") or ""
        if not title or not href:
            return None

        salary = item.get("salary") or {}
        currency = _CURRENCY_MAP.get((salary.get("currency") or "").lower())
        company = ((item.get("company") or {}).get("title") or "").strip()
        published = (item.get("publishedDate") or {}).get("date")

        skills = [s.get("title", "") for s in (item.get("skills") or []) if isinstance(s, dict)]
        divisions = [d.get("title", "") for d in (item.get("divisions") or []) if isinstance(d, dict)]

        return {
            "external_id": str(item.get("id", "")),
            "title": title,
            "company": company,
            "salary_min": salary.get("from"),
            "salary_max": salary.get("to"),
            "currency": currency,
            "location": ", ".join(filter(None, [item.get("location") or ""])),
            "work_format": "Удалёнка" if item.get("remoteWork") else None,
            "url": href if href.startswith("http") else BASE + href,
            "description": "",
            "snippet": " | ".join(filter(None, [", ".join(divisions), ", ".join(skills)])),
            "published_at": published,
        }
