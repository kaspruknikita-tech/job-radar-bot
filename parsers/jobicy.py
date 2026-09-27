"""
Парсер jobicy.com через публичный JSON API.

GET /api/v2/remote-jobs?tag=<маска>&count=N — работают также industry= и geo=.
Отдаёт полное описание, компанию, регион и дату публикации.

Выдача сильно смещена в сторону США: гео-скоринг сам опустит такие вакансии,
поэтому дополнительно тянем ленту industry=management без гео-фильтра.
"""

import logging
import time

import requests

import config
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

API_URL = "https://jobicy.com/api/v2/remote-jobs"
REQUEST_DELAY = 0.5
REQUEST_TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

TAGS = P.SEARCH_JOBICY_TAGS  # правится в profile/profile.py


class JobicyParser(BaseParser):
    source_name = "jobicy"
    channel = "global"

    def fetch(self) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()

        queries = [{"tag": t} for t in TAGS] + [{"industry": "management"}]
        for params in queries:
            for job in self._request({**params, "count": config.JOBICY_COUNT}):
                jid = str(job.get("id", ""))
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                v = self._parse(job)
                if v:
                    out.append(v)

        logger.info("[jobicy] Получено вакансий: %d", len(out))
        return out

    def _request(self, params: dict) -> list[dict]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(API_URL, headers=_HEADERS, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("jobs") or []
        except (requests.RequestException, ValueError):
            logger.warning("[jobicy] Ошибка запроса params=%s", params)
            return []

    @staticmethod
    def _parse(job: dict) -> dict | None:
        title = (job.get("jobTitle") or "").strip()
        url = (job.get("url") or "").strip()
        if not title or not url:
            return None

        salary_min = job.get("salaryMin")
        salary_max = job.get("salaryMax")
        try:
            salary_min = int(float(salary_min)) if salary_min else None
            salary_max = int(float(salary_max)) if salary_max else None
        except (ValueError, TypeError):
            salary_min = salary_max = None

        return {
            "external_id": str(job.get("id", "")),
            "title": title,
            "company": (job.get("companyName") or "").strip(),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": (job.get("salaryCurrency") or "").upper() or None,
            "location": (job.get("jobGeo") or "").strip(),
            "work_format": "Удалёнка",
            "url": url,
            "description": job.get("jobDescription") or job.get("jobExcerpt") or "",
            "published_at": job.get("pubDate"),
        }
