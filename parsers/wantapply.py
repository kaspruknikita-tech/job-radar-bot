"""
Парсер wantapply.com.
Публичный API: api.wantapply.com/api/v1/jobs
Категории: ux-researcher, customer-support
"""

import logging

import requests

from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

API_URL = "https://api.wantapply.com/api/v1/jobs"
CATEGORIES = P.SEARCH_WANTAPPLY_CATEGORIES  # правится в profile/profile.py
MAX_PAGES = 10
PAGE_SIZE = 100

TITLE_WHITELIST = P.SEARCH_WANTAPPLY_TITLES  # правится в profile/profile.py

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://wantapply.com/",
    "Origin": "https://wantapply.com",
}


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in TITLE_WHITELIST)


def _extract_location(job: dict) -> str:
    locations = job.get("jobLocations") or []
    if locations and isinstance(locations[0], dict):
        return locations[0].get("name") or locations[0].get("city") or ""
    regions = job.get("jobRegions") or []
    if regions and isinstance(regions[0], dict):
        return regions[0].get("name") or ""
    return ""


class WantapplyParser(BaseParser):
    source_name = "wantapply"
    channel = "global"

    def fetch(self) -> list[dict]:
        result = []
        seen: set[str] = set()

        for category in CATEGORIES:
            logger.info("[wantapply] Категория: %s", category)
            for page_num in range(1, MAX_PAGES + 1):
                try:
                    resp = requests.get(
                        API_URL,
                        params={"page": page_num, "limit": PAGE_SIZE, "category": category},
                        headers=_HEADERS,
                        timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except requests.RequestException:
                    logger.exception("[wantapply] Ошибка запроса, категория=%s стр=%d", category, page_num)
                    break

                jobs = data.get("data") or []
                if not jobs:
                    break

                for job in jobs:
                    title = job.get("title", "").strip()
                    if not _is_relevant(title):
                        continue

                    job_id = str(job.get("id") or "")
                    if job_id in seen:
                        continue
                    seen.add(job_id)

                    slug = job.get("url") or ""
                    job_url = f"https://wantapply.com/{slug}" if slug else ""

                    result.append({
                        "external_id": job_id,
                        "title": title,
                        "company": job.get("companyName") or "",
                        "salary_min": job.get("salaryMin"),
                        "salary_max": job.get("salaryMax"),
                        "currency": job.get("salaryCurrency"),
                        "location": _extract_location(job),
                        "work_format": None,
                        "url": job_url,
                        "description": job.get("description") or "",
                    })

                if not data.get("hasNextPage"):
                    break

        logger.info("[wantapply] Итого: %d вакансий", len(result))
        return result
