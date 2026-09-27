"""
Парсер cryptojobslist.com — доска crypto/web3-вакансий.

Публичного API нет: /api/ и страницы /jobs/<slug> закрыты Cloudflare (403
"Just a moment…"). Надёжно отдаётся только SSR главной страницы со списком
последних вакансий, встроенным в <script id="__NEXT_DATA__"> (Next.js).
Пагинация — через ?page=N (тоже SSR, отдаёт следующие 25).

Источник listing-only: детальная страница недоступна, поэтому описание не
берём (в листинге оно — заглушка "<title> at <company>. Read more…").
Релевантность определяем по title (whitelist) + дизайнерским тегам.

Зарплата реальная (per-job, не глобальный фейк-дефолт). Заполняем
salary_min/max ТОЛЬКО для unitText=YEAR — чтобы не смешивать месячные/часовые
суммы с годовыми из других источников. Зарплату не нормализуем (см. память).
"""

import json
import logging
import re

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://cryptojobslist.com"
MAX_PAGES = 10
PAGE_TIMEOUT = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Точный whitelist по title. Без голых "research"/"researcher" (на крипто-доске
# это в основном quant/token research, не UX — UX-роли ловятся по "ux"/"user
# research"/"design researcher") и без голых "ui"/"designer" ("ui" ловит
# "guidance"/"build", "designer" на этой доске — бренд/гейм-дизайн).
WHITELIST = [
    "ux", "cx", "usability",
    "user experience", "customer experience", "user research",
    "service designer", "product designer", "ui designer", "ui/ux",
    "design researcher", "ux strategist", "research ops", "voice of customer",
]

# Точные дизайнерские теги. Тег "designer" не берём — навешан на бренд/гейм/
# графику; "research" — на sales/business-development.
DESIGN_TAGS = {"ui-ux", "product-design"}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _is_relevant(title: str, tags: list) -> bool:
    t = title.lower()
    if any(w in t for w in WHITELIST):
        return True
    return bool(DESIGN_TAGS & {str(x).lower() for x in (tags or [])})


def _parse_salary(salary: dict | None) -> tuple[int | None, int | None, str | None]:
    """salary (schema.org-подобный) → (min, max, currency). Только YEAR."""
    if not salary:
        return None, None, None
    if (salary.get("unitText") or "").upper() != "YEAR":
        return None, None, None
    currency = (salary.get("currency") or "").strip().upper() or None
    try:
        smin = int(float(salary["minValue"])) if salary.get("minValue") else None
        smax = int(float(salary["maxValue"])) if salary.get("maxValue") else None
    except (ValueError, TypeError):
        return None, None, None
    return smin, smax, (currency if (smin or smax) else None)


def _job_url(job: dict, slug: str) -> str:
    raw_ld = job.get("jobPostingJSONLD")
    if isinstance(raw_ld, str):
        try:
            graph = (json.loads(raw_ld).get("@graph") or [{}])[0]
            if graph.get("url"):
                return graph["url"]
        except json.JSONDecodeError:
            pass
    return f"{BASE}/jobs/{slug}" if slug else BASE


def _map_job(job: dict) -> dict | None:
    if job.get("filled") or job.get("isActive") is False:
        return None

    title = (job.get("jobTitle") or "").strip()
    if not title or not _is_relevant(title, job.get("tags")):
        return None

    slug = job.get("seoSlug") or ""
    external_id = slug or str((job.get("_id") or {}).get("$oid") or job.get("id") or "")

    smin, smax, currency = _parse_salary(job.get("salary"))

    remote = bool(job.get("remote"))
    location = (job.get("jobLocation") or "").strip()
    if not location and remote:
        location = "Remote"

    return {
        "external_id": external_id,
        "title": title,
        "company": (job.get("companyName") or "").strip(),
        "salary_min": smin,
        "salary_max": smax,
        "currency": currency,
        "location": location,
        "work_format": "Remote" if remote else None,
        "url": _job_url(job, slug),
        # Описание недоступно (детальная страница за Cloudflare) — не выдумываем.
        "description": "",
    }


class CryptoJobsListParser(BaseParser):
    source_name = "cryptojobslist"
    channel = "global"
    # url вакансии — страница cryptojobslist (за Cloudflare), не ATS-борд;
    # apply-ссылок в листинге нет → авто-харвест ATS бесполезен.
    harvest_ats = False

    def fetch(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(_HEADERS)

        result = []
        seen = set()
        for page in range(1, MAX_PAGES + 1):
            url = BASE if page == 1 else f"{BASE}/?page={page}"
            try:
                resp = session.get(url, timeout=PAGE_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                logger.warning("[cryptojobslist] Ошибка запроса стр=%d", page)
                break

            m = _NEXT_DATA_RE.search(resp.text)
            if not m:
                logger.warning("[cryptojobslist] Нет __NEXT_DATA__ на стр=%d", page)
                break
            try:
                pp = json.loads(m.group(1))["props"]["pageProps"]
            except (json.JSONDecodeError, KeyError):
                logger.warning("[cryptojobslist] Не разобрал __NEXT_DATA__ стр=%d", page)
                break

            jobs = pp.get("jobs") or []
            if not jobs:
                break

            for job in jobs:
                parsed = _map_job(job)
                if not parsed:
                    continue
                key = parsed["external_id"] or parsed["url"]
                if key in seen:
                    continue
                seen.add(key)
                result.append(parsed)

            total_pages = (pp.get("meta") or {}).get("totalPages")
            if total_pages and page >= total_pages:
                break

        logger.info("[cryptojobslist] Итого после whitelist: %d вакансий", len(result))
        return result
