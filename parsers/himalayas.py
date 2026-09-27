"""
Парсер RemoteOK.com (замена Himalayas — у него нет публичного API).
API: https://remoteok.com/api
Публичный, без ключей. Возвращает JSON-массив (первый элемент — метаданные).
"""

import logging

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"

WHITELIST = ["researcher", "research", "ux", "cx", "insight", "usability"]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


class HimalayasParser(BaseParser):
    source_name = "remoteok"
    channel = "global"

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(
                API_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://remoteok.com/",
                    "Origin": "https://remoteok.com",
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("[remoteok] Ошибка запроса: %s — status=%s",
                         e, getattr(getattr(e, 'response', None), 'status_code', '?'))
            return []

        result = []
        for job in data:
            if not isinstance(job, dict) or "id" not in job:
                continue
            title = job.get("position", "")
            if not _is_relevant(title):
                continue
            result.append({
                "external_id": str(job.get("id", "")),
                "title": title,
                "company": job.get("company", ""),
                "salary_min": job.get("salary_min") or None,
                "salary_max": job.get("salary_max") or None,
                "currency": "USD" if job.get("salary_min") or job.get("salary_max") else None,
                "location": job.get("location", ""),
                "work_format": "Remote",
                "url": job.get("url", ""),
                "description": job.get("description", ""),
            })

        return result
