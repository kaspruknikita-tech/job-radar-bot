"""
Парсер Working Nomads.
API: https://www.workingnomads.com/api/exposed_jobs/
Публичный, без ключей. Один GET отдаёт весь список.
"""

import logging

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://www.workingnomads.com/api/exposed_jobs/"

WHITELIST = ["researcher", "research", "ux", "cx", "insight", "usability"]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


class WorkingNomadsParser(BaseParser):
    source_name = "workingnomads"
    channel = "global"

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(API_URL, timeout=15)
            resp.raise_for_status()
            jobs = resp.json()
        except requests.RequestException:
            logger.exception("[workingnomads] Ошибка запроса")
            return []

        result = []
        for job in jobs:
            title = job.get("title", "")
            if not _is_relevant(title):
                continue
            result.append({
                "external_id": str(job.get("id", "")),
                "title": title,
                "company": job.get("company_name", ""),
                "salary_min": None,
                "salary_max": None,
                "currency": None,
                "location": job.get("location", ""),
                "work_format": "Remote",
                "url": job.get("url", ""),
                "description": job.get("description", ""),
            })

        return result
