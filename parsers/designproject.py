"""
Парсер designproject.io/jobs.
Публичного API нет — парсим SSR HTML листинга и детальной страницы.
Карточки листинга: title, company, salary, дата.
Детальная: location, work_format, applyUrl, description (из og:description).
"""

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from parsers.base import BaseParser
from tools.ats_harvest import harvest_ats_tokens

logger = logging.getLogger(__name__)

BASE_URL = "https://designproject.io/jobs/"
MAX_PAGES = 50
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

_SALARY_RE = re.compile(
    r"\$?(?P<min>\d+(?:[.,]\d+)?)\s*k?\s*-\s*\$?(?P<max>\d+(?:[.,]\d+)?)\s*k?"
    r"\s*/?\s*(?P<period>hour|year|month|week)?",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"\(([A-Z]{3})\)")
_APPLY_URL_RE = re.compile(r'applyUrl\\":\\"(?P<url>[^"\\]+)\\"')
_WORK_FORMAT_RE = re.compile(r"\b(Remote|Hybrid|Onsite|On-site)\b", re.IGNORECASE)
_LOCATION_RE = re.compile(
    r"(?:Remote|Hybrid|Onsite|On-site)\s+position\s+in\s+([^.]+?)\.",
    re.IGNORECASE,
)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _parse_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """`$80-100/hour (USD)` или `$129k-195k/year (USD)` → (min, max, currency)."""
    if not text:
        return None, None, None
    m = _SALARY_RE.search(text)
    if not m:
        return None, None, None
    try:
        smin = float(m.group("min").replace(",", ""))
        smax = float(m.group("max").replace(",", ""))
    except ValueError:
        return None, None, None
    if "k" in text.lower().split("/", 1)[0]:
        smin *= 1000
        smax *= 1000
    cur_m = _CURRENCY_RE.search(text)
    currency = cur_m.group(1) if cur_m else None
    return int(smin), int(smax), currency


def _parse_card(card) -> dict | None:
    href = card.get("href", "")
    if not href.startswith("/jobs/"):
        return None
    slug = href.removeprefix("/jobs/")
    if "/" in slug or not slug:
        return None

    h2 = card.find("h2")
    if not h2:
        return None
    title = h2.get_text(strip=True)

    company_el = card.select_one("div.text-sm")
    company = company_el.get_text(strip=True) if company_el else ""

    salary_text = ""
    for span in card.select("span.whitespace-nowrap"):
        txt = span.get_text(strip=True)
        if "$" in txt or "€" in txt or "£" in txt:
            salary_text = txt
            break
    smin, smax, currency = _parse_salary(salary_text)

    return {
        "external_id": slug,
        "title": title,
        "company": company,
        "salary_min": smin,
        "salary_max": smax,
        "currency": currency,
        "url": f"https://designproject.io/jobs/{slug}",
    }


def _enrich_from_detail(vacancy: dict, html: str) -> None:
    soup = BeautifulSoup(html, "html.parser")

    og_desc_el = soup.find("meta", attrs={"property": "og:description"})
    og_desc = og_desc_el.get("content", "") if og_desc_el else ""

    wf_m = _WORK_FORMAT_RE.search(og_desc)
    vacancy["work_format"] = wf_m.group(1).capitalize() if wf_m else None

    loc_m = _LOCATION_RE.search(og_desc)
    vacancy["location"] = loc_m.group(1).strip() if loc_m else ""

    apply_m = _APPLY_URL_RE.search(html)
    if apply_m:
        apply_url = apply_m.group("url").replace("\\u0026", "&")
        vacancy["url"] = apply_url

    vacancy["description"] = og_desc


class DesignprojectParser(BaseParser):
    source_name = "designproject"
    channel = "global"
    harvest_ats = False  # свой ручной харвест (см. fetch)

    def fetch(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(_HEADERS)

        candidates: list[dict] = []
        seen_slugs: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            try:
                resp = session.get(BASE_URL, params={"page": page}, timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.exception("[designproject] Ошибка листинга, стр=%d", page)
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("a.job-card[href^='/jobs/']")
            if not cards:
                logger.info("[designproject] Стр %d пуста, стоп", page)
                break

            page_added = 0
            for card in cards:
                parsed = _parse_card(card)
                if not parsed:
                    continue
                if parsed["external_id"] in seen_slugs:
                    continue
                seen_slugs.add(parsed["external_id"])
                if not _is_relevant(parsed["title"]):
                    continue
                candidates.append(parsed)
                page_added += 1

            logger.debug("[designproject] Стр %d: +%d матчей", page, page_added)

        logger.info("[designproject] Кандидатов после whitelist: %d", len(candidates))

        result = []
        for v in candidates:
            try:
                resp = session.get(v["url"], timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
                _enrich_from_detail(v, resp.text)
            except requests.RequestException:
                logger.warning("[designproject] Не удалось обогатить %s", v["external_id"])
                v.setdefault("location", "")
                v.setdefault("work_format", None)
                v.setdefault("description", "")
            result.append(v)

        logger.info("[designproject] Итого: %d вакансий", len(result))

        # Apply-URL ведёт на реальный ATS (ashby/greenhouse/lever) — харвестим
        # токены компаний, чтобы чистый ATS-парсер тянул их напрямую, а не фейк
        # от designproject. См. кейс Hinge Health.
        try:
            harvest_ats_tokens([v["url"] for v in result if v.get("url")],
                               source_label="designproject")
        except Exception:
            logger.exception("[designproject] Сбой авто-харвеста ATS, продолжаем")

        return result
