"""
Парсер Remotive.com.
API: https://remotive.com/api/remote-jobs
Публичный, без ключей. Один запрос на цикл (rate limit: 2 req/min).
Параметр search= по факту не фильтрует — фильтруем по заголовку сами.
Задержка вакансий: 24 часа.
"""

import logging

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"

TITLE_WHITELIST = [
    "researcher", "research", "ux", "cx",
    "insight", "insights", "usability",
    "service designer", "voice of customer",
    "ux strategist", "research ops",
    "cx analyst", "customer experience",
]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in TITLE_WHITELIST)


class RemotiveParser(BaseParser):
    source_name = "remotive"
    channel = "global"

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(API_URL, timeout=15)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except requests.RequestException:
            logger.exception("[remotive] Ошибка запроса")
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
                "location": job.get("candidate_required_location", ""),
                "work_format": None,
                "url": job.get("url", ""),
                "description": job.get("description", ""),
            })

        return result
