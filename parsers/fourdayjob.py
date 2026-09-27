"""
Парсер 4dayjob.com — вакансии с 4-дневной рабочей неделей.
API закрыт (robots Disallow /api/), список вакансий рендерится клиентом,
поэтому идём через sitemap.xml → отдельные /job/<slug> с JSON-LD JobPosting (SSR).

Двухуровневый фильтр:
  1. грубый префильтр по токенам слага (граница по "-") — чтобы не качать все 1000 страниц;
  2. точный фильтр по реальному title из JSON-LD.
"""

import json
import logging
import re
from datetime import datetime, timezone

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://www.4dayjob.com"
SITEMAP_URL = f"{BASE}/sitemap.xml"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Токены слага для грубого префильтра (сравнение по целым словам, не подстрокам —
# иначе "ux" ловит "linux" и случайные суффиксы вроде "-uxgff").
SLUG_TOKENS = {
    "ux", "ui", "cx", "research", "researcher", "usability",
    "insights", "insight", "experience",
}

# Точный whitelist по реальному title (как в remotive/workingnomads).
TITLE_WHITELIST = [
    "researcher", "research", "ux", "cx",
    "insight", "insights", "usability",
    "service designer", "voice of customer",
    "ux strategist", "research ops",
    "cx analyst", "customer experience",
]


def _slug_prefilter(slug: str) -> bool:
    tokens = {t.lower() for t in slug.split("-")}
    return bool(tokens & SLUG_TOKENS)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in TITLE_WHITELIST)


def _job_slugs(sitemap_xml: str) -> list[str]:
    return sorted(set(re.findall(r"/job/([a-zA-Z0-9-]+)", sitemap_xml)))


def _parse_jobposting(html: str) -> dict | None:
    for block in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "JobPosting":
            return data
    return None


def _is_expired(data: dict) -> bool:
    """True, если validThrough в прошлом — вакансия протухла."""
    raw = data.get("validThrough", "")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt < datetime.now(timezone.utc)


def _location(data: dict) -> str:
    # addressCountry на сайте всегда "US" (мусорный дефолт) — не используем.
    if data.get("jobLocationType") == "TELECOMMUTE":
        req = data.get("applicantLocationRequirements") or {}
        country = req.get("name", "")
        return f"Remote {country}".strip()
    addr = (data.get("jobLocation") or {}).get("address") or {}
    return addr.get("addressLocality", "") or ""


class FourDayJobParser(BaseParser):
    source_name = "4dayjob"
    channel = "global"

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("[4dayjob] Ошибка запроса sitemap")
            return []

        slugs = [s for s in _job_slugs(resp.text) if _slug_prefilter(s)]
        logger.info("[4dayjob] Кандидатов после префильтра: %d", len(slugs))

        result = []
        for slug in slugs:
            url = f"{BASE}/job/{slug}"
            try:
                page = requests.get(url, headers=HEADERS, timeout=15)
                page.raise_for_status()
            except requests.RequestException:
                logger.warning("[4dayjob] Не удалось получить %s", url)
                continue

            data = _parse_jobposting(page.text)
            if not data:
                continue

            title = data.get("title", "")
            if not _is_relevant(title):
                continue

            if _is_expired(data):
                continue

            result.append({
                "external_id": slug,
                "title": title,
                "company": (data.get("hiringOrganization") or {}).get("name", ""),
                # Зарплату не берём: на сайте у всех вакансий фейковый дефолт 50k–150k USD.
                "salary_min": None,
                "salary_max": None,
                "currency": None,
                "location": _location(data),
                "work_format": "Remote" if data.get("jobLocationType") == "TELECOMMUTE" else None,
                "url": data.get("url") or url,
                "description": data.get("description", ""),
            })

        return result
