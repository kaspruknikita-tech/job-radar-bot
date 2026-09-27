"""
Парсер BambooHR Careers (публичная часть, без авторизации).
List:   https://{token}.bamboohr.com/careers/list           -> {result: [...]}
Detail: https://{token}.bamboohr.com/careers/{id}/detail     -> {result: {jobOpening: {...}}}

ВАЖНО: несуществующий субдомен отдаёт 302 на www.bamboohr.com, поэтому
существование борда = 200 + наличие ключа result (см. validate_bamboohr).
"""

import logging

import requests

from parsers._ats_tokens import merge_companies
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

LIST_URL = "https://{token}.bamboohr.com/careers/list"
DETAIL_URL = "https://{token}.bamboohr.com/careers/{job_id}/detail"
REQUEST_TIMEOUT = 20


def all_companies() -> list[str]:
    """SEED (COMPANIES) + авто-найденные токены из БД."""
    return merge_companies(COMPANIES, "bamboohr")


# Верифицированные субдомены (API: 200 + result). Токен = поддомен careers.
COMPANIES = [
    "headspin", "testgrid", "profinda", "lullabot", "knack",
    "modern", "precisionnutrition", "thegrid", "tortuga",
]

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


def _extract_location(job: dict) -> str:
    if job.get("isRemote"):
        return "Remote"
    loc = job.get("location") or {}
    ats = job.get("atsLocation") or {}
    parts = [
        loc.get("city") or ats.get("city"),
        loc.get("state") or ats.get("state"),
        ats.get("country"),
    ]
    return ", ".join(p for p in parts if p)


def _fetch_detail(token: str, job_id: str) -> dict:
    """jobOpening из detail-эндпоинта (description, url, location). {} при ошибке."""
    try:
        resp = requests.get(DETAIL_URL.format(token=token, job_id=job_id), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return (resp.json().get("result", {}) or {}).get("jobOpening", {}) or {}
    except requests.RequestException:
        return {}


class BambooHRParser(BaseParser):
    source_name = "bamboohr"
    channel = "global"
    harvest_ats = False  # сам ATS — url уже его токен

    def fetch(self) -> list[dict]:
        result = []
        for token in all_companies():
            url = LIST_URL.format(token=token)
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
                if resp.status_code != 200:
                    continue
                data = resp.json()
            except requests.RequestException as e:
                logger.warning(
                    "[bamboohr] %s — ошибка: %s",
                    token,
                    getattr(getattr(e, "response", None), "status_code", str(e)),
                )
                continue
            except ValueError:
                continue

            for job in data.get("result", []):
                title = job.get("jobOpeningName", "")
                if not _is_relevant(title):
                    continue
                job_id = str(job.get("id", ""))
                detail = _fetch_detail(token, job_id)
                job_url = detail.get("jobOpeningShareUrl") or f"https://{token}.bamboohr.com/careers/{job_id}"
                description = detail.get("description", "") or ""
                location = _extract_location(detail) or _extract_location(job)
                result.append({
                    "external_id": job_id,
                    "title": title,
                    "company": token.capitalize(),
                    "salary_min": None,
                    "salary_max": None,
                    "currency": None,
                    "location": location,
                    "work_format": "Remote" if (detail.get("isRemote") or job.get("isRemote")) else "",
                    "url": job_url,
                    "description": description,
                })

        return result
