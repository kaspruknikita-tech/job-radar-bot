"""
Парсер uxwork.nl — нидерландская доска UX-вакансий (EN-версия).
Публичного API нет. Вход — SSR-листинги категорий /en/jobs-category/<cat>/,
оттуда собираем ссылки /en/job/<slug>_<id>/. Детальная страница содержит
структурированный JSON-LD JobPosting (schema.org) — берём поля оттуда.

Зарплата: baseSalary бывает помесячной (типично для NL). Схема БД хранит
суммы без периода, поэтому заполняем salary_min/max ТОЛЬКО для unitText=YEAR,
иначе None — чтобы не смешивать месячные суммы с годовыми из других источников.
Зарплату не нормализуем (см. память проекта).

Apply-ссылка ведёт на сайт работодателя — собираем для авто-харвеста ATS-токенов
вручную (harvest_ats=False, т.к. url вакансии — страница uxwork, не ATS).
"""

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from parsers.base import BaseParser
from tools.ats_harvest import harvest_ats_tokens

logger = logging.getLogger(__name__)

BASE = "https://uxwork.nl"
CATEGORIES = [
    "conversation-design", "content-design", "digital-design", "motion-design",
    "product-design", "service-design", "ui-design", "ux-design",
    "ux_ui-design", "ux-leadership", "ux-research", "ux-writing", "visual-design",
]
MAX_PAGES = 5
PAGE_TIMEOUT = 20

WHITELIST = [
    "researcher", "research", "ux", "cx", "usability",
    "service designer", "voice of customer", "ux strategist",
    "research ops", "customer experience", "insight",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_JOB_HREF_RE = re.compile(r"https://uxwork\.nl/en/job/[^\"'#?]+")
_JOB_ID_RE = re.compile(r"_(\d+)/?$")
_CITY_RE = re.compile(r"\(([^)]+)\)")
_WORK_FORMAT_RE = re.compile(r"\b(Remote|Hybrid|Onsite|On-site)\b", re.IGNORECASE)

_CURRENCY_MAP = {"EURO": "EUR", "EUROS": "EUR", "€": "EUR"}


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _collect_job_urls(session: requests.Session) -> set[str]:
    urls: set[str] = set()
    for cat in CATEGORIES:
        for page in range(1, MAX_PAGES + 1):
            path = f"/en/jobs-category/{cat}/"
            if page > 1:
                path += f"page/{page}/"
            try:
                resp = session.get(BASE + path, timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.warning("[uxwork] Ошибка листинга %s стр=%d", cat, page)
                break

            found = set(_JOB_HREF_RE.findall(resp.text))
            if not found:
                break
            new = found - urls
            urls |= found
            logger.debug("[uxwork] %s стр %d: +%d (новых %d)",
                         cat, page, len(found), len(new))
            if not new:  # страница не дала новых ссылок — дальше нет смысла
                break
    logger.info("[uxwork] Уникальных вакансий в листингах: %d", len(urls))
    return urls


def _parse_salary(base_salary: dict | None) -> tuple[int | None, int | None, str | None]:
    """baseSalary (schema.org MonetaryAmount) → (min, max, currency).
    Заполняем суммы только для годового периода (см. docstring модуля)."""
    if not base_salary:
        return None, None, None
    value = base_salary.get("value") or {}
    if (value.get("unitText") or "").upper() != "YEAR":
        return None, None, None
    raw_cur = (base_salary.get("currency") or "").strip().upper()
    currency = _CURRENCY_MAP.get(raw_cur, raw_cur or None)
    try:
        smin = int(float(value["minValue"])) if value.get("minValue") else None
        smax = int(float(value["maxValue"])) if value.get("maxValue") else None
    except (ValueError, TypeError):
        return None, None, None
    return smin, smax, (currency if (smin or smax) else None)


def _parse_detail(url: str, html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    ld_el = soup.find("script", attrs={"type": "application/ld+json"})
    if not ld_el or not ld_el.string:
        return None
    try:
        d = json.loads(ld_el.string)
    except json.JSONDecodeError:
        return None
    if d.get("@type") != "JobPosting":
        return None

    title = (d.get("title") or "").strip()
    if not title or not _is_relevant(title):
        return None

    id_m = _JOB_ID_RE.search(url)
    external_id = id_m.group(1) if id_m else (d.get("identifier") or {}).get("value", "")

    company = (d.get("hiringOrganization") or {}).get("name", "").strip()

    address = (d.get("jobLocation") or {}).get("address") or {}
    location = (address.get("addressLocality") or "").strip()
    if not location:
        og = soup.find("meta", attrs={"property": "og:title"})
        city_m = _CITY_RE.search(og.get("content", "")) if og else None
        location = city_m.group(1).strip() if city_m else (address.get("addressCountry") or "").strip()

    desc_html = d.get("description") or ""
    description = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)

    wf_m = _WORK_FORMAT_RE.search(description)
    work_format = wf_m.group(1).capitalize() if wf_m else None

    smin, smax, currency = _parse_salary(d.get("baseSalary"))

    # apply-ссылка работодателя — для авто-харвеста ATS-токенов
    apply_el = soup.select_one("a.solliciteer-link[href^='http']")
    apply_url = apply_el.get("href") if apply_el else None

    return {
        "external_id": external_id,
        "title": title,
        "company": company,
        "salary_min": smin,
        "salary_max": smax,
        "currency": currency,
        "location": location,
        "work_format": work_format,
        "url": url,
        "description": description,
        "_apply_url": apply_url,
    }


class UxworkParser(BaseParser):
    source_name = "uxwork"
    channel = "global"
    harvest_ats = False  # свой ручной харвест apply-ссылок (см. fetch)

    def fetch(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(_HEADERS)

        job_urls = _collect_job_urls(session)

        result = []
        apply_urls = []
        for url in job_urls:
            try:
                resp = session.get(url, timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.warning("[uxwork] Не удалось забрать %s", url)
                continue
            parsed = _parse_detail(url, resp.text)
            if not parsed:
                continue
            apply = parsed.pop("_apply_url", None)
            if apply:
                apply_urls.append(apply)
            result.append(parsed)

        logger.info("[uxwork] Итого после whitelist: %d вакансий", len(result))

        if apply_urls:
            try:
                harvest_ats_tokens(apply_urls, source_label="uxwork")
            except Exception:
                logger.exception("[uxwork] Сбой авто-харвеста ATS, продолжаем")

        return result
