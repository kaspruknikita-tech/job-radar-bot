"""
Ночной probe ATS-токенов по именам компаний из свежих вакансий.

Логика:
1. Берём названия компаний из vacancies за последние сутки.
2. Отсеиваем уже покрытые (seed + БД) и уже опробованные (ats_probed_names).
3. По каждому новому имени генерим slug-маски и стучимся в ATS API.
4. Валидные токены → в БД, КАЖДУЮ попытку фиксируем в ats_probed_names.

Дедуп через ats_probed_names обязателен: ~21 HTTP/имя (маски × 3 ATS),
без него ночь за ночью долбили бы одни и те же промахи.
"""

import logging
from datetime import datetime, timedelta, timezone

import database
from parsers.ashby import all_companies as ashby_companies
from parsers.greenhouse import all_companies as gh_companies
from parsers.lever import all_companies as lever_companies
from parsers.smartrecruiters import all_companies as sr_companies
from parsers.bamboohr import all_companies as bamboohr_companies
from tools.discover_ats_by_name import (
    candidates,
    check_ashby,
    check_bamboohr,
    check_gh,
    check_lever,
    check_smartrecruiters,
)

logger = logging.getLogger(__name__)

_CHECKERS = {
    "ashby": check_ashby,
    "greenhouse": check_gh,
    "lever": check_lever,
    "smartrecruiters": check_smartrecruiters,
    "bamboohr": check_bamboohr,
}
_COMPANY_LOADERS = {
    "ashby": ashby_companies,
    "greenhouse": gh_companies,
    "lever": lever_companies,
    "smartrecruiters": sr_companies,
    "bamboohr": bamboohr_companies,
}


def run_night_probe(since_hours: int = 24, limit: int = 0) -> dict[str, list[str]]:
    """Возвращает {ats: [новые токены]}. limit>0 — максимум имён за прогон."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=since_hours)
    names = database.get_recent_companies(start, end)
    if limit:
        names = names[:limit]

    covered = {ats: {t.lower() for t in loader()} for ats, loader in _COMPANY_LOADERS.items()}
    probed = database.get_probed_pairs()
    found: dict[str, list[str]] = {ats: [] for ats in _CHECKERS}

    logger.info("[night_probe] имён за %dч: %d", since_hours, len(names))
    for name in names:
        cands = candidates(name)
        for ats, check in _CHECKERS.items():
            if (name.lower(), ats) in probed:
                continue
            fresh = [c for c in cands if c.lower() not in covered[ats]]
            if not fresh:
                # все маски уже в seed/БД — компания покрыта, больше не возвращаемся
                database.record_probed_name(name, ats, "covered")
                continue
            hit = next((c for c in fresh if check(c)), None)
            if hit:
                database.save_ats_token(ats, hit, source="night_probe")
                database.record_probed_name(name, ats, f"hit:{hit}")
                covered[ats].add(hit.lower())
                found[ats].append(hit)
                logger.info("[night_probe] %s: %s -> %s", ats, name, hit)
            else:
                database.record_probed_name(name, ats, "miss")

    total = sum(len(v) for v in found.values())
    logger.info("[night_probe] новых токенов: %d %s", total, found)
    return found
