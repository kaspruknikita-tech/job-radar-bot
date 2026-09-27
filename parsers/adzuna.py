"""
Парсер Adzuna Jobs API.
Документация: https://developer.adzuna.com/activedocs
Требует ADZUNA_APP_ID и ADZUNA_APP_KEY.
Агрегатор: миллионы вакансий из 11+ стран.
"""

import logging
import time

import requests

import config
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
REQUEST_DELAY = 0.5

COUNTRIES = ["gb", "us", "de", "nl", "au", "ca", "fr", "sg", "at", "pl"]

# Adzuna отдаёт зарплату в валюте страны запроса, а не в USD.
COUNTRY_CURRENCY = {
    "gb": "GBP",
    "us": "USD",
    "de": "EUR",
    "nl": "EUR",
    "fr": "EUR",
    "at": "EUR",
    "au": "AUD",
    "ca": "CAD",
    "sg": "SGD",
    "pl": "PLN",
}

SEARCH_QUERIES = [
    "ux researcher",
    "user researcher",
    "cx researcher",
    "customer researcher",
    "insights researcher",
    "usability researcher",
    "design researcher",
]


class AdzunaParser(BaseParser):
    source_name = "adzuna"
    channel = "global"

    def fetch(self) -> list[dict]:
        if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
            logger.warning("[adzuna] ADZUNA_APP_ID или ADZUNA_APP_KEY не заданы")
            return []

        result = []
        seen_ids: set[str] = set()

        for country in COUNTRIES:
            for query in SEARCH_QUERIES:
                jobs = self._search(country, query)
                for job in jobs:
                    vid = str(job.get("id", ""))
                    if not vid or vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    location_parts = job.get("location", {}).get("area", [])
                    location = ", ".join(location_parts[-2:]) if location_parts else ""

                    salary_min = job.get("salary_min")
                    salary_max = job.get("salary_max")

                    result.append({
                        "external_id": vid,
                        "title": job.get("title", ""),
                        "company": (job.get("company") or {}).get("display_name", ""),
                        "salary_min": int(salary_min) if salary_min else None,
                        "salary_max": int(salary_max) if salary_max else None,
                        "currency": "GBP" if country == "gb" else "USD",
                        "location": location,
                        "work_format": None,
                        "url": job.get("redirect_url", ""),
                        "description": job.get("description", ""),
                    })
                time.sleep(REQUEST_DELAY)

        return result

    def _search(self, country: str, query: str) -> list[dict]:
        url = BASE_URL.format(country=country)
        try:
            resp = requests.get(
                url,
                params={
                    "app_id": config.ADZUNA_APP_ID,
                    "app_key": config.ADZUNA_APP_KEY,
                    "what": query,
                    "results_per_page": 50,
                    "content-type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except requests.RequestException:
            logger.exception("[adzuna] Ошибка запроса: country=%s query=%s", country, query)
            return []
