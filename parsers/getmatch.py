"""
Парсер getmatch.ru через публичный JSON API.

GET /api/offers?offset=N — лента офферов (limit фиксирован 20, сортировка
от свежих). Поиска и фильтров у эндпоинта нет, поэтому забираем ленту
целиком до GETMATCH_MAX_OFFERS и отсеиваем уже своим белым списком.

Полезная особенность источника: у офферов есть english_level — дописываем
его в описание, чтобы скоринг видел требование к языку.
"""

import logging
import time

import requests

import config
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://getmatch.ru/api/offers"
BASE = "https://getmatch.ru"
PAGE_SIZE = 20
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_FORMAT_MAP = {"remote": "Удалёнка", "hybrid": "Гибрид", "office": "Офис", "on_site": "Офис"}


class GetmatchParser(BaseParser):
    source_name = "getmatch"
    channel = "ru"

    def fetch(self) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while offset < config.GETMATCH_MAX_OFFERS:
            offers = self._page(offset)
            if not offers:
                break
            for o in offers:
                v = self._parse(o)
                if v:
                    out.append(v)
            offset += PAGE_SIZE
        logger.info("[getmatch] Получено офферов: %d", len(out))
        return out

    def _page(self, offset: int) -> list[dict]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(
                API_URL, headers=_HEADERS, params={"offset": offset},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("offers") or []
        except (requests.RequestException, ValueError):
            logger.warning("[getmatch] Ошибка запроса offset=%d", offset)
            return []

    @staticmethod
    def _parse(o: dict) -> dict | None:
        title = (o.get("position") or "").strip()
        if not title or not o.get("is_active", True):
            return None

        company = ((o.get("company") or {}).get("name") or "").strip()

        items = o.get("location_items") or []
        labels = [i.get("label", "") for i in items if isinstance(i, dict) and not i.get("exclude")]
        formats = {i.get("format") for i in items if isinstance(i, dict)}
        work_format = None
        for key in ("remote", "hybrid", "office", "on_site"):
            if key in formats:
                work_format = _FORMAT_MAP[key]
                break

        description = o.get("offer_description") or o.get("description_html") or ""
        english = o.get("english_level")
        if english:
            description = f"{description}\n\nУровень английского: {english}"

        url = o.get("url") or ""
        return {
            "external_id": str(o.get("id", "")),
            "title": title,
            "company": company,
            "salary_min": o.get("salary_display_from"),
            "salary_max": o.get("salary_display_to"),
            "currency": o.get("salary_currency"),
            "location": ", ".join(l for l in labels if l),
            "work_format": work_format,
            "url": url if url.startswith("http") else BASE + url,
            "description": description,
            "published_at": o.get("published_at"),
        }
