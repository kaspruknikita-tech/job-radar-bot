"""
Парсер LinkedIn Jobs через библиотеку python-jobspy (github.com/Bunsly/JobSpy).
Тянет вакансии с гостевых job-эндпоинтов LinkedIn — без логина под аккаунтом.

Важно про прод:
- LinkedIn агрессивно режет запросы с дата-центровых IP (Railway). Без
  резидентных прокси быстро ловит 429/пустые ответы. Прокси задаются в
  JOBSPY_PROXIES (список через запятую), локально можно без них на малом объёме.
- linkedin_fetch_description=True делает +1 запрос на вакансию (нужно для
  скоринга по JD), но заметно медленнее и чувствительнее к rate-limit.
"""

import logging
import re

import config
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

# Сигналы доступности для аудитории СНГ (remote / hybrid / виза / релокейт).
# Дешёвый гейт на уровне парсинга: ловит явные упоминания в тексте вакансии.
# НЕ заменяет LLM-скоринг — там точная классификация remote_policy/visa.
_ACCESS_RE = re.compile(
    r"\b(remote|hybrid|work from home|wfh|distributed|work from anywhere|"
    r"visa|sponsor|sponsorship|relocat)",
    re.IGNORECASE,
)


def _is_accessible(row: dict) -> bool:
    """True, если вакансия похожа на remote/hybrid/визовую/релокейт."""
    if row.get("is_remote"):
        return True
    text = " ".join(str(row.get(f) or "") for f in ("title", "job_type", "description"))
    return bool(_ACCESS_RE.search(text))

SEARCH_TERMS = P.SEARCH_LINKEDIN  # правится в profile/profile.py


class JobSpyLinkedInParser(BaseParser):
    source_name = "linkedin"
    channel = "global"
    # url = job_url_direct → прямой career-сайт компании, полезно для ATS-дискавери.
    harvest_ats = True

    def fetch(self) -> list[dict]:
        try:
            from jobspy import scrape_jobs
        except ImportError:
            logger.error("[linkedin] python-jobspy не установлен — пропускаю источник")
            return []

        proxies = config.JOBSPY_PROXIES or None
        locations = config.JOBSPY_LOCATIONS or [None]
        results_wanted = config.JOBSPY_RESULTS_WANTED
        hours_old = config.JOBSPY_HOURS_OLD or None
        fetch_desc = config.JOBSPY_FETCH_DESCRIPTION

        seen: set[str] = set()
        result: list[dict] = []

        # LinkedIn отдаёт вакансии по одной локации на запрос → перебираем гео × термины.
        for location in locations:
            # "Remote" как локация = remote-вакансии независимо от страны.
            is_remote = isinstance(location, str) and location.lower() == "remote"
            loc_arg = None if is_remote else location
            for term in SEARCH_TERMS:
                try:
                    df = scrape_jobs(
                        site_name=["linkedin"],
                        search_term=term,
                        location=loc_arg,
                        is_remote=is_remote,
                        results_wanted=results_wanted,
                        hours_old=hours_old,
                        linkedin_fetch_description=fetch_desc,
                        proxies=proxies,
                    )
                except Exception:
                    logger.exception(
                        "[linkedin] Ошибка scrape_jobs (loc=%r term=%r)", location, term
                    )
                    continue

                if df is None or df.empty:
                    continue

                for row in df.to_dict("records"):
                    ext_id = str(row.get("id") or "")
                    if ext_id and ext_id in seen:
                        continue
                    if ext_id:
                        seen.add(ext_id)

                    # Гейт доступности (remote/hybrid/виза/релокейт) до скоринга.
                    if config.JOBSPY_ACCESS_FILTER and not _is_accessible(row):
                        continue

                    url = row.get("job_url_direct") or row.get("job_url") or ""
                    # числа не нормализуем; NaN/0 → None
                    smin = _num(row.get("min_amount"))
                    smax = _num(row.get("max_amount"))

                    result.append({
                        "external_id": ext_id,
                        "title": row.get("title") or "",
                        "company": row.get("company") or "",
                        "salary_min": smin,
                        "salary_max": smax,
                        "currency": _clean(row.get("currency")),
                        "location": _clean(row.get("location")) or "",
                        "work_format": "remote" if row.get("is_remote") else "",
                        "url": url,
                        "description": row.get("description") or "",
                    })

        return result


def _num(v):
    """min/max amount → int или None (отсекаем NaN и нули)."""
    try:
        if v is None:
            return None
        f = float(v)
        if f != f or f <= 0:  # NaN или 0
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _clean(v):
    """pandas может отдать NaN (float) вместо строки."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    s = str(v).strip()
    return s or None
