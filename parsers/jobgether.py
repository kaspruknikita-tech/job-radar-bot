"""
Парсер jobgether.com — агрегатор remote-вакансий (200k+, все профессии).
Публичного API нет. Вход — SSR-листинг поиска
/search-offers?keyword=<kw>&page=<n>, оттуда собираем ссылки /offer/<id>-<slug>.
Детальная страница содержит несколько JSON-LD блоков — берём именно JobPosting.

Источник шумный (агрегатор), поэтому ищем только узкими research-фразами и
дополнительно фильтруем по whitelist в title (голый "research" даёт quant/
data-entry/AI-research-engineer). Часть вакансий дублирует первоисточники
(greenhouse/lever/ashby) — кросс-источниковые дубли хэш не схлопнёт.

Зарплата: baseSalary часто отсутствует; как и в uxwork, заполняем суммы только
для годового периода (unitText=YEAR). Зарплату не нормализуем (память проекта).

hiringOrganization.sameAs ведёт на реальный сайт работодателя — собираем для
авто-харвеста ATS-токенов вручную (harvest_ats=False: url вакансии — страница
jobgether, не ATS). Cloudflare: соблюдаем crawl-delay из robots.txt.
"""

import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from parsers.base import BaseParser
from tools.ats_harvest import harvest_ats_tokens

logger = logging.getLogger(__name__)

BASE = "https://jobgether.com"
KEYWORDS = [
    "ux researcher", "user researcher", "design researcher",
    "usability researcher", "ux research", "user research",
]
MAX_PAGES = 2
PAGE_TIMEOUT = 20
REQUEST_DELAY = 2.0  # robots.txt: Crawl-delay: 2

WHITELIST = [
    "researcher", "ux", "cx", "usability", "user experience",
    "customer experience", "design research", "research ops",
    "voice of customer", "ux strategist", "insight",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# /offer/<24-hex-id>-<slug> ; "undefined" — битые карточки, отсекаем
_OFFER_HREF_RE = re.compile(r"/offer/([a-f0-9]{24})-[a-z0-9-]+")
_WORK_FORMAT_RE = re.compile(r"\b(Remote|Hybrid|Onsite|On-site)\b", re.IGNORECASE)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _find_job_posting(soup: BeautifulSoup) -> dict | None:
    """На странице несколько JSON-LD — возвращаем блок с @type=JobPosting."""
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


def _collect_offer_urls(session: requests.Session) -> set[str]:
    urls: set[str] = set()
    for kw in KEYWORDS:
        for page in range(1, MAX_PAGES + 1):
            params = {"keyword": kw}
            if page > 1:
                params["page"] = page
            try:
                resp = session.get(BASE + "/search-offers", params=params,
                                   timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.warning("[jobgether] Ошибка листинга kw=%r стр=%d", kw, page)
                break

            found = {BASE + m.group(0) for m in _OFFER_HREF_RE.finditer(resp.text)}
            new = found - urls
            urls |= found
            logger.debug("[jobgether] kw=%r стр %d: +%d (новых %d)",
                         kw, page, len(found), len(new))
            time.sleep(REQUEST_DELAY)
            if not new:  # страница не дала новых ссылок — дальше нет смысла
                break
    logger.info("[jobgether] Уникальных вакансий в листингах: %d", len(urls))
    return urls


def _parse_salary(base_salary: dict | None) -> tuple[int | None, int | None, str | None]:
    """baseSalary (schema.org MonetaryAmount) → (min, max, currency).
    Заполняем суммы только для годового периода (см. docstring модуля)."""
    if not base_salary:
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


def _parse_detail(url: str, html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    d = _find_job_posting(soup)
    if not d:
        return None

    title = (d.get("title") or "").strip()
    if not title or not _is_relevant(title):
        return None

    id_m = _OFFER_HREF_RE.search(url)
    external_id = id_m.group(1) if id_m else ""

    org = d.get("hiringOrganization") or {}
    company = (org.get("name") or "").strip()
    company_site = org.get("sameAs")  # реальный сайт работодателя → харвест ATS

    # локация: страна из applicantLocationRequirements, иначе из jobLocation
    location = ""
    reqs = d.get("applicantLocationRequirements")
    if isinstance(reqs, list) and reqs:
        location = (reqs[0].get("name") or "").strip()
    if not location:
        jl = d.get("jobLocation")
        jl0 = jl[0] if isinstance(jl, list) and jl else (jl or {})
        location = ((jl0.get("address") or {}).get("addressCountry") or "").strip()

    desc_html = d.get("description") or ""
    description = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)

    if (d.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        work_format = "Remote"
    else:
        wf_m = _WORK_FORMAT_RE.search(description)
        work_format = wf_m.group(1).capitalize() if wf_m else None

    smin, smax, currency = _parse_salary(d.get("baseSalary"))

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
        "_company_site": company_site,
    }


class JobgetherParser(BaseParser):
    source_name = "jobgether"
    channel = "global"
    harvest_ats = False  # свой ручной харвест sameAs-ссылок (см. fetch)

    def fetch(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(_HEADERS)

        offer_urls = _collect_offer_urls(session)

        result = []
        company_sites = []
        for url in offer_urls:
            try:
                resp = session.get(url, timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.warning("[jobgether] Не удалось забрать %s", url)
                continue
            time.sleep(REQUEST_DELAY)
            parsed = _parse_detail(url, resp.text)
            if not parsed:
                continue
            site = parsed.pop("_company_site", None)
            if site:
                company_sites.append(site)
            result.append(parsed)

        logger.info("[jobgether] Итого после whitelist: %d вакансий", len(result))

        if company_sites:
            try:
                harvest_ats_tokens(company_sites, source_label="jobgether")
            except Exception:
                logger.exception("[jobgether] Сбой авто-харвеста ATS, продолжаем")

        return result
