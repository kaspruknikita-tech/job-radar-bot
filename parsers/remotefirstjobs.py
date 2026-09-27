"""
Парсер Remote First Jobs (remotefirstjobs.com).
API: https://remotefirstjobs.com/api/search-jobs — публичный JSON, без ключей.
Агрегатор 21k+ career-страниц → попутно дискавери ATS-токенов через харвест.
Условия источника: вакансии отдаём 24ч после публикации; нужен кредит + ссылка
на их URL (см. поле url). Макс 5 страниц по 100 вакансий на запрос.
"""

import logging

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://remotefirstjobs.com/api/search-jobs"
CATEGORY = "design"
MAX_PAGES = 5  # лимит источника

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


class RemoteFirstJobsParser(BaseParser):
    source_name = "remotefirstjobs"
    channel = "global"

    def fetch(self) -> list[dict]:
        result = []
        for page in range(MAX_PAGES):
            try:
                resp = requests.get(
                    API_URL,
                    params={"category": CATEGORY, "page": page},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                resp.raise_for_status()
                jobs = resp.json().get("jobs", [])
            except requests.RequestException:
                logger.exception("[remotefirstjobs] Ошибка запроса (page=%d)", page)
                break

            if not jobs:
                break

            for job in jobs:
                title = job.get("title", "")
                if not _is_relevant(title):
                    continue
                locations = job.get("locations") or []
                location = ", ".join(loc for loc in locations if loc)
                # 0 = зарплата не указана; числа не нормализуем
                smin = job.get("salary_min") or None
                smax = job.get("salary_max") or None
                result.append({
                    "external_id": str(job.get("id", "")),
                    "title": title,
                    "company": job.get("company_name", ""),
                    "salary_min": smin,
                    "salary_max": smax,
                    "currency": None,
                    "location": location,
                    "work_format": "remote",
                    "url": job.get("url", ""),
                    "description": job.get("description", ""),
                })

            if len(jobs) < 100:
                break

        return result
