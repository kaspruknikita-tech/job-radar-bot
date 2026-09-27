"""
Парсер gamejobs.co — вакансии в геймдеве (домен профиля).

У борда есть Atom-фид (/?format=atom) со 100 свежими записями: оттуда берём
ссылки и даты. Описание — JSON-LD JobPosting на детальной странице.
"""

import logging
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from filters.stopwords import apply_filters
from parsers._html_board import find_job_posting, ld_location
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

FEED_URL = "https://gamejobs.co/?format=atom"
_NS = {"a": "http://www.w3.org/2005/Atom"}
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20
MAX_VACANCIES = 40

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class GameJobsParser(BaseParser):
    source_name = "gamejobs"
    channel = "global"

    def fetch(self) -> list[dict]:
        entries = self._feed()
        logger.info("[gamejobs] Записей в фиде: %d", len(entries))

        out: list[dict] = []
        for entry in entries:
            # Заголовок в фиде — «<роль> at <компания>», по нему и фильтруем
            # до детального запроса.
            if not apply_filters({"title": entry["title"]}) or self.is_known(entry["url"]):
                continue
            v = self._detail(entry)
            if v:
                out.append(v)
            if len(out) >= MAX_VACANCIES:
                break
        logger.info("[gamejobs] Релевантных вакансий: %d", len(out))
        return out

    def _feed(self) -> list[dict]:
        try:
            resp = requests.get(FEED_URL, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except (requests.RequestException, ET.ParseError):
            logger.warning("[gamejobs] Не удалось получить Atom-фид")
            return []

        out = []
        for e in root.findall("a:entry", _NS):
            title_el = e.find("a:title", _NS)
            link_el = e.find("a:link", _NS)
            updated_el = e.find("a:updated", _NS)
            if title_el is None or link_el is None:
                continue
            out.append({
                "title": (title_el.text or "").strip(),
                "url": link_el.get("href", ""),
                "updated": updated_el.text if updated_el is not None else None,
            })
        return out

    def _detail(self, entry: dict) -> dict | None:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(entry["url"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return None

        d = find_job_posting(BeautifulSoup(resp.text, "html.parser"))
        if not d:
            return None

        org = d.get("hiringOrganization")
        company = (org.get("name") or "").strip() if isinstance(org, dict) else ""
        return {
            "external_id": entry["url"],
            "title": (d.get("title") or entry["title"]).strip(),
            "company": company,
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "location": ld_location(d),
            "work_format": None,
            "url": entry["url"],
            "description": d.get("description") or "",
            "published_at": d.get("datePosted") or entry.get("updated"),
        }
