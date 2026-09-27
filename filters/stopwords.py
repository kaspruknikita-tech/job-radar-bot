"""
Фильтрация вакансий.

Подход: БЕЛЫЙ СПИСОК — вакансия проходит, только если в заголовке
есть хотя бы одно из разрешённых слов. Всё остальное — мусор.
Проще и надёжнее, чем бесконечный список стоп-фраз.

Профиль: Technical PM / Delivery / Operations (архетипы TPM, DEL, OPS, PERF, TRANS).
"""

import logging
import re

from langdetect import detect, LangDetectException

from user_profile import P

logger = logging.getLogger(__name__)

WHITELIST = P.WHITELIST  # правится в profile/profile.py

# Граница слова ПЕРЕД токеном: 'ops' матчит 'product ops', но не 'devops'-хвост
# внутри слова. Суффикс разрешён: 'operation' матчит 'operations'.
_WHITELIST_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in WHITELIST) + r")",
    re.IGNORECASE,
)

# Стоп-роли профиля. Проверяются ПЕРВЫМИ, до белого списка.
BLACKLIST = P.BLACKLIST

# Та же логика границы, что у белого списка: 'hr' не должен ловить 'threshold',
# 'ui' — 'building', 'ux' — 'luxury'. Суффикс свободен: 'designer' ловит 'designers'.
_BLACKLIST_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in BLACKLIST) + r")",
    re.IGNORECASE,
)

# Тестирование — не профиль. Отдельно от BLACKLIST: «qa» нужно по границам слова с обеих сторон.
_QA_RE = re.compile(r"\b(qa|aqa|sdet)\b|тестировщ|тестирован", re.IGNORECASE)


def stop_role(title: str) -> str | None:
    """Сработавшая стоп-роль в заголовке или None. Используется и при отборе, и при скоринге
    уже сохранённых вакансий — чтобы новое стоп-правило действовало и на очередь."""
    title = title or ""
    match = _BLACKLIST_RE.search(title) or _QA_RE.search(title)
    return match.group(0) if match else None


COMPANY_BLACKLIST: set[str] = set()



def _is_allowed_language(vacancy: dict) -> bool:
    # Берём только description/snippet — заголовок слишком короткий для надёжного определения
    text = " ".join(filter(None, [
        vacancy.get("snippet", ""),
        vacancy.get("description", ""),
    ]))
    if len(text) < 50:
        return True
    try:
        lang = detect(text)
        return lang in ("en", "ru")
    except LangDetectException:
        return True


def apply_filters(vacancy: dict) -> bool:
    """True = вакансия прошла фильтр."""
    title = (vacancy.get("title") or "").lower()

    # 1. Чёрный список — проверяем первым
    stop = stop_role(title)
    if stop:
        logger.debug("Чёрный список '%s': %s", stop, vacancy.get("title"))
        return False

    # 2. Белый список — должно быть хотя бы одно слово (по границе слова)
    if not _WHITELIST_RE.search(title):
        logger.debug("Не прошёл белый список: %s", vacancy.get("title"))
        return False

    # 3. Язык — только английский/русский (Greenhouse всегда EN, пропускаем)
    if vacancy.get("source") != "greenhouse" and not _is_allowed_language(vacancy):
        logger.debug("Не английский язык: %s", vacancy.get("title"))
        return False

    return True
