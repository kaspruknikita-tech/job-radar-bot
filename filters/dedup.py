"""
Дедупликация вакансий.
Проверяет по хэшу, а также по external_id+source (для переходного периода,
когда в базе лежат старые хэши по URL, а новые — по external_id).
"""

import logging

import database

logger = logging.getLogger(__name__)


def is_duplicate(vacancy: dict) -> bool:
    """Возвращает True, если вакансия уже есть в базе."""
    title = vacancy.get("title")
    company = vacancy.get("company")

    if database.vacancy_exists(vacancy.get("hash", "")):
        logger.debug("Дубликат (hash): %s (%s)", title, company)
        return True

    external_id = vacancy.get("external_id")
    source = vacancy.get("source")
    if external_id and source and database.vacancy_exists_by_external(external_id, source):
        logger.debug("Дубликат (external_id): %s (%s)", title, company)
        return True

    if title and company and database.vacancy_exists_by_title_company(title, company):
        logger.debug("Дубликат (title+company): %s (%s)", title, company)
        return True

    return False
