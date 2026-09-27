"""
Парсер Arbeitnow.com.
API: https://www.arbeitnow.com/api/job-board-api
Публичный, без ключей. Возвращает JSON с массивом data, поддерживает пагинацию.
"""

import logging
import time

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 15
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

WHITELIST = [
    "researcher", "research", "ux", "cx",
    "insight", "usability",
    "service designer", "voice of customer",
    "ux strategist", "research ops",
    "cx analyst", "customer experience",
]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


class ArbeitnowParser(BaseParser):
    source_name = "arbeitnow"
    channel = "global"

    def _fetch_page(self, page: int) -> list[dict] | None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    API_URL, params={"page": page},
                    headers=HEADERS, timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 403:
                    err_type, err_detail = "Cloudflare403", resp.text[:80]
                elif resp.status_code == 429:
                    err_type, err_detail = "RateLimit429", resp.headers.get("Retry-After", "?")
                else:
                    resp.raise_for_status()
                    return resp.json().get("data", [])
            except requests.Timeout:
                err_type, err_detail = "Timeout", f"{REQUEST_TIMEOUT}s"
            except requests.RequestException as e:
                err_type, err_detail = e.__class__.__name__, str(e)[:80]

            if attempt < MAX_RETRIES:
                logger.info("[arbeitnow] стр %d: %s %s, retry %d/%d через %ds",
                            page, err_type, err_detail, attempt, MAX_RETRIES, RETRY_BACKOFF_SEC)
                time.sleep(RETRY_BACKOFF_SEC)
            else:
                logger.warning("[arbeitnow] стр %d: %s %s (исчерпаны попытки)",
                               page, err_type, err_detail)
        return None

    def fetch(self) -> list[dict]:
        result = []
        for page in range(1, MAX_PAGES + 1):
            jobs = self._fetch_page(page)
            if jobs is None:
                break

            if not jobs:
                break

            for job in jobs:
                title = job.get("title", "")
                if not _is_relevant(title):
                    continue
                result.append({
                    "external_id": str(job.get("slug", "")),
                    "title": title,
                    "company": job.get("company_name", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "currency": None,
                    "location": job.get("location", ""),
                    "work_format": None,
                    "url": job.get("url", ""),
                    "description": job.get("description", ""),
                })

        return result
