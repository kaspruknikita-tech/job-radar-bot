"""
Парсер RemoteOK — публичный JSON API.
GET https://remoteok.com/api — список remote-вакансий.
item[0] — метаданные (legal terms), остальные — вакансии.
"""

import logging

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-ux-jobs/1.0)"}

WHITELIST = [
    "ux researcher", "ux research",
    "user researcher", "user research",
    "product researcher", "design researcher",
    "usability researcher", "usability research",
    "cx researcher", "cx research",
    "consumer insights", "user insights",
    "ux writer", "content designer",
    "usability", "user experience researcher",
]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


class RemoteOKParser(BaseParser):
    source_name = "remoteok"
    channel = "global"

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(API_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[remoteok] ошибка: %s", e)
            return []

        result = []
        for job in data[1:]:  # пропускаем item[0] = метаданные
            title = (job.get("position") or "").strip()
            if not _is_relevant(title):
                continue
            result.append({
                "external_id": str(job.get("id", "")),
                "title": title,
                "company": (job.get("company") or "").strip(),
                "salary_min": job.get("salary_min"),
                "salary_max": job.get("salary_max"),
                "currency": "USD" if job.get("salary_min") else None,
                "location": (job.get("location") or "").strip(),
                "work_format": "Remote",
                "url": job.get("url") or job.get("apply_url", ""),
                "description": job.get("description", ""),
            })
        return result
