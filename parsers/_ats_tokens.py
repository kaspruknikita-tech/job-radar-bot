"""
Объединяет SEED-список токенов (захардкожен в парсере, лежит в git) с
авто-найденными токенами из БД. БД нужна потому, что на Railway ФС эфемерная —
дозапись в parsers/*.py стирается при редеплое.
"""

import logging

import database

logger = logging.getLogger(__name__)


def merge_companies(seed: list[str], ats: str) -> list[str]:
    """SEED + токены из БД, дедуп регистронезависимо, порядок: сперва seed.
    При недоступной БД возвращает голый seed — парсер не должен падать из-за этого."""
    try:
        db_tokens = database.load_ats_tokens(ats)
    except Exception:
        logger.exception("[%s] не удалось прочитать токены из БД, беру только seed", ats)
        db_tokens = []

    seen: set[str] = set()
    out: list[str] = []
    for t in list(seed) + db_tokens:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out
