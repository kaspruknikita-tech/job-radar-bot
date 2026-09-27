"""
Парсер remoterocketship.com.

Данные лежат в __NEXT_DATA__ (props.pageProps.initialJobOpenings) — 20 вакансий
на страницу, с прямой ссылкой на отклик у работодателя, компанией, локацией,
типом занятости и требуемыми языками.

Ищем по маскам должностей (jobTitle=...), сортировка от свежих.
"""

import json
import logging
import time

import requests
from bs4 import BeautifulSoup

import config
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

BASE = "https://www.remoterocketship.com"
REQUEST_DELAY = 0.6
REQUEST_TIMEOUT = 25

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

JOB_TITLES = P.SEARCH_REMOTEROCKETSHIP  # правится в profile/profile.py

_FORMAT_MAP = {"remote": "Удалёнка", "hybrid": "Гибрид", "onsite": "Офис", "on_site": "Офис"}


class RemoteRocketshipParser(BaseParser):
    source_name = "remoterocketship"
    channel = "global"

    def fetch(self) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()

        for title in JOB_TITLES:
            for page in range(1, config.REMOTEROCKETSHIP_MAX_PAGES + 1):
                jobs = self._page(title, page)
                if not jobs:
                    break
                for j in jobs:
                    jid = str(j.get("id", ""))
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)
                    v = self._parse(j)
                    if v:
                        out.append(v)

        logger.info("[remoterocketship] Получено вакансий: %d", len(out))
        return out

    def _page(self, job_title: str, page: int) -> list[dict]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(
                BASE, headers=_HEADERS,
                params={"page": page, "sort": "DateAdded", "jobTitle": job_title},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("[remoterocketship] Ошибка запроса %r стр=%d", job_title, page)
            return []

        el = BeautifulSoup(resp.text, "html.parser").find("script", id="__NEXT_DATA__")
        if not el or not el.string:
            return []
        try:
            data = json.loads(el.string)
        except json.JSONDecodeError:
            return []
        return data.get("props", {}).get("pageProps", {}).get("initialJobOpenings") or []

    @staticmethod
    def _parse(j: dict) -> dict | None:
        title = (j.get("roleTitle") or "").strip()
        url = (j.get("url") or "").strip()
        if not title or not url:
            return None
        if j.get("dateDeleted"):
            return None

        company = ((j.get("company") or {}).get("name") or "").strip()
        location = ", ".join(filter(None, [
            j.get("locationCity") or "", j.get("location") or "",
        ]))

        description = " ".join(filter(None, [
            j.get("jobDescriptionSummary") or "",
            j.get("twoLineJobDescriptionSummary") or "",
        ]))
        salary = j.get("salaryRange")
        if salary:
            description += f"\n\nSalary range: {salary}"
        languages = j.get("requiredLanguages")
        if languages:
            description += f"\n\nRequired languages: {', '.join(languages)}"

        return {
            "external_id": str(j.get("id", "")),
            "title": title,
            "company": company,
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "location": location,
            "work_format": _FORMAT_MAP.get((j.get("locationType") or "").lower()),
            "url": url,
            "description": description,
            "published_at": j.get("created_at"),
        }
