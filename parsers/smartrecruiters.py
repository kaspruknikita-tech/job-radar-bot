"""
Парсер SmartRecruiters Posting API.
Публичный, без авторизации. Итерируется по списку компаний.
List:   https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset=N
Detail: https://api.smartrecruiters.com/v1/companies/{token}/postings/{id}  (описание)

ВАЖНО: API отдаёт 200 на любой токен (даже несуществующий), поэтому
существование борда определяется по totalFound>0 — см. validate_smartrecruiters.
"""

import logging

import requests

from parsers._ats_tokens import merge_companies
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset={offset}"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{token}/postings/{job_id}"
REQUEST_TIMEOUT = 20
MAX_PAGES = 10  # 100×10 = потолок 1000 вакансий на борд


def all_companies() -> list[str]:
    """SEED (COMPANIES) + авто-найденные токены из БД."""
    return merge_companies(COMPANIES, "smartrecruiters")


# Верифицированные токены (API: totalFound>0). Регистрозависимы.
COMPANIES = [
    "servicenow", "doit", "instructure", "intevity",
    "judgeme", "nearform", "timedoctor",
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
    loc = job.get("location", {}) or {}
    full = loc.get("fullLocation")
    if full:
        return full
    parts = [loc.get("city"), loc.get("country", "").upper()]
    return ", ".join(p for p in parts if p)


def _extract_work_format(job: dict) -> str:
    loc = job.get("location", {}) or {}
    if loc.get("remote"):
        return "Remote"
    if loc.get("hybrid"):
        return "Hybrid"
    return ""


def _section_text(sections: dict, key: str) -> str:
    return (sections.get(key) or {}).get("text", "") or ""


def _fetch_detail(token: str, job_id: str) -> tuple[str, str]:
    """Возвращает (url, description_html). При ошибке — ('', '')."""
    try:
        resp = requests.get(DETAIL_URL.format(token=token, job_id=job_id), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        d = resp.json()
    except requests.RequestException:
        return "", ""
    url = d.get("postingUrl") or d.get("applyUrl") or ""
    sec = (d.get("jobAd", {}) or {}).get("sections", {}) or {}
    description = "\n".join(
        t for t in (
            _section_text(sec, "jobDescription"),
            _section_text(sec, "qualifications"),
            _section_text(sec, "additionalInformation"),
        ) if t
    )
    return url, description


class SmartRecruitersParser(BaseParser):
    source_name = "smartrecruiters"
    channel = "global"
    harvest_ats = False  # сам ATS — url уже его токен

    def fetch(self) -> list[dict]:
        result = []
        for token in all_companies():
            for offset in range(0, MAX_PAGES * 100, 100):
                url = LIST_URL.format(token=token, offset=offset)
                try:
                    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
                    resp.raise_for_status()
                    data = resp.json()
                except requests.RequestException as e:
                    logger.warning(
                        "[smartrecruiters] %s — ошибка: %s",
                        token,
                        getattr(getattr(e, "response", None), "status_code", str(e)),
                    )
                    break

                content = data.get("content", [])
                if not content:
                    break

                for job in content:
                    title = job.get("name", "")
                    if not _is_relevant(title):
                        continue
                    job_id = str(job.get("id", ""))
                    job_url, description = _fetch_detail(token, job_id)
                    company = (job.get("company", {}) or {}).get("name") or token.capitalize()
                    result.append({
                        "external_id": job_id,
                        "title": title,
                        "company": company,
                        "salary_min": None,
                        "salary_max": None,
                        "currency": None,
                        "location": _extract_location(job),
                        "work_format": _extract_work_format(job),
                        "url": job_url,
                        "description": description,
                    })

                if offset + 100 >= data.get("totalFound", 0):
                    break

        return result
