"""
Парсер geekjob.ru.

Список — недокументированный, но публичный JSON: /json/find/vacancy?page=N
(~260 вакансий на 3 страницах, описания в нём нет).

Описание тянем с детальной /vacancy/<id>: сначала JSON-LD JobPosting,
фолбэк — блок #vacancy-description. Детальную дёргаем ТОЛЬКО для вакансий,
прошедших белый список, — иначе 260 лишних запросов за цикл.
"""

import json
import logging
import time

import requests
from bs4 import BeautifulSoup

from filters.stopwords import apply_filters
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://geekjob.ru"
LIST_URL = f"{BASE}/json/find/vacancy"
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20
MAX_PAGES = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _job_format(fmt: dict) -> str | None:
    if not isinstance(fmt, dict):
        return None
    if fmt.get("remote"):
        return "Удалёнка"
    if fmt.get("inhouse"):
        return "Офис"
    return None


class GeekjobParser(BaseParser):
    source_name = "geekjob"
    channel = "ru"

    def fetch(self) -> list[dict]:
        raw: list[dict] = []
        page = 1
        while page <= MAX_PAGES:
            data = self._page(page)
            if not data:
                break
            raw.extend(data.get("data") or [])
            nxt = data.get("nextpage")
            if not nxt or nxt <= page:
                break
            page = nxt

        vacancies = [v for v in (self._parse(item) for item in raw) if v]
        # Детальные страницы только для релевантных — экономим запросы.
        relevant = [v for v in vacancies if apply_filters(v) and not self.is_known(v["external_id"])]
        logger.info("[geekjob] В листинге %d, релевантных %d", len(vacancies), len(relevant))

        for v in relevant:
            self._enrich(v)
        return relevant

    def _page(self, page: int) -> dict | None:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(LIST_URL, headers=_HEADERS, params={"page": page},
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError):
            logger.warning("[geekjob] Ошибка листинга стр=%d", page)
            return None

    def _enrich(self, v: dict) -> None:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(v["url"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.debug("[geekjob] не открылась детальная %s", v["url"])
            return

        soup = BeautifulSoup(resp.text, "html.parser")

        for el in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not el.string:
                continue
            try:
                d = json.loads(el.string)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                v["description"] = d.get("description") or v["description"]
                v["published_at"] = d.get("datePosted") or v.get("published_at")
                return

        block = soup.select_one("#vacancy-description") or soup.select_one(".description")
        if block:
            v["description"] = str(block)

    @staticmethod
    def _parse(item: dict) -> dict | None:
        title = (item.get("position") or "").strip()
        vid = str(item.get("id", ""))
        if not title or not vid:
            return None

        location = ", ".join(filter(None, [item.get("city") or "", item.get("country") or ""]))
        return {
            "external_id": vid,
            "title": title,
            "company": ((item.get("company") or {}).get("name") or "").strip(),
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "location": location,
            "work_format": _job_format(item.get("jobFormat")),
            "url": f"{BASE}/vacancy/{vid}",
            "description": "",
            "snippet": item.get("salary") or "",
            "published_at": None,
        }
