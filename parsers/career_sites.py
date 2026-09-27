"""
Парсер карьерных сайтов компаний из реестра career_sites.

Берём только те компании, у которых не нашлось ATS-борда (greenhouse/ashby/…):
их вакансии иначе не увидит никто. Реестр наполняет tools/hypercareer_companies.py.

Схема: карьерная страница → ссылки, похожие на вакансию → JSON-LD JobPosting.
Сайты на SPA без JSON-LD не отдадут ничего — это ожидаемо, заглушек не делаем.

За один цикл обходим ограниченное число компаний (CAREER_SITES_PER_CYCLE),
список перемешиваем — за несколько циклов реестр обходится целиком.
"""

import json
import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

import config
import database
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Ссылки, похожие на карточку вакансии.
_JOB_HREF_RE = re.compile(
    r"/(?:job|jobs|vacancy|vacancies|career|careers|position|positions|opening|openings|role|roles)/",
    re.IGNORECASE,
)
_REQUEST_DELAY = 0.4
_PAGE_TIMEOUT = 12
_MAX_JOB_PAGES = 25


def _get(url: str) -> str | None:
    try:
        time.sleep(_REQUEST_DELAY)
        resp = requests.get(url, headers=_HEADERS, timeout=_PAGE_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        logger.debug("[career_sites] не открылась %s", url)
        return None


def _find_job_posting(soup: BeautifulSoup) -> dict | None:
    """JSON-LD блок с @type=JobPosting. Учитываем @graph и массивы."""
    for el in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not el.string:
            continue
        try:
            d = json.loads(el.string)
        except json.JSONDecodeError:
            continue
        items = d.get("@graph", [d]) if isinstance(d, dict) else d
        for it in items if isinstance(items, list) else [items]:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


def _parse_salary(base_salary: dict | None) -> tuple[int | None, int | None, str | None]:
    """baseSalary (schema.org) → (min, max, currency). Только годовой период —
    смешивать месяц с годом в одной колонке нельзя."""
    if not isinstance(base_salary, dict):
        return None, None, None
    value = base_salary.get("value") or {}
    if (value.get("unitText") or "").upper() != "YEAR":
        return None, None, None
    currency = (base_salary.get("currency") or "").strip().upper() or None
    try:
        smin = int(float(value["minValue"])) if value.get("minValue") else None
        smax = int(float(value["maxValue"])) if value.get("maxValue") else None
    except (ValueError, TypeError):
        return None, None, None
    return smin, smax, (currency if (smin or smax) else None)


def _location(d: dict) -> str:
    loc = d.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address")
    if not isinstance(addr, dict):
        return ""
    parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
    parts = [p for p in parts if isinstance(p, str) and p.strip()]
    return ", ".join(parts)


def _to_vacancy(d: dict, url: str, company_fallback: str) -> dict | None:
    title = (d.get("title") or "").strip()
    if not title:
        return None

    org = d.get("hiringOrganization")
    company = ""
    if isinstance(org, dict):
        company = (org.get("name") or "").strip()

    smin, smax, currency = _parse_salary(d.get("baseSalary"))
    return {
        "external_id": url,
        "title": title,
        "company": company or company_fallback,
        "salary_min": smin,
        "salary_max": smax,
        "currency": currency,
        "location": _location(d),
        "work_format": None,
        "url": url,
        "description": d.get("description") or "",
        "published_at": d.get("datePosted"),
    }


class CareerSitesParser(BaseParser):
    source_name = "career_sites"
    channel = "ru"

    def fetch(self) -> list[dict]:
        try:
            companies = database.load_career_sites(only_without_ats=True)
        except Exception:
            logger.exception("[career_sites] не удалось прочитать реестр")
            return []

        if not companies:
            logger.info("[career_sites] реестр пуст — нечего обходить")
            return []

        random.shuffle(companies)
        limit = config.CAREER_SITES_PER_CYCLE
        companies = companies[:limit]
        logger.info("[career_sites] компаний в этом цикле: %d", len(companies))

        vacancies: list[dict] = []
        for c in companies:
            vacancies.extend(self._fetch_company(c))
        return vacancies

    def _fetch_company(self, company: dict) -> list[dict]:
        url = company.get("url") or ""
        if not url.startswith(("http://", "https://")):
            return []

        html = _get(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: list[dict] = []

        # Иногда JSON-LD лежит прямо на странице списка.
        posting = _find_job_posting(soup)
        if posting:
            v = _to_vacancy(posting, url, company["name"])
            if v:
                out.append(v)

        from urllib.parse import urljoin, urlparse
        base_host = urlparse(url).netloc
        job_urls = []
        for a in soup.find_all("a", href=True):
            full = urljoin(url, a["href"])
            if urlparse(full).netloc != base_host:
                continue
            if _JOB_HREF_RE.search(full) and full != url:
                job_urls.append(full)

        seen = set()
        for job_url in job_urls:
            if job_url in seen or self.is_known(job_url):
                continue
            seen.add(job_url)
            if len(seen) > _MAX_JOB_PAGES:
                break
            page = _get(job_url)
            if not page:
                continue
            d = _find_job_posting(BeautifulSoup(page, "html.parser"))
            if not d:
                continue
            v = _to_vacancy(d, job_url, company["name"])
            if v:
                out.append(v)

        if out:
            logger.info("[career_sites] %s: вакансий %d", company["name"], len(out))
        return out
