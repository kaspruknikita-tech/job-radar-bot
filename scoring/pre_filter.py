from __future__ import annotations

import re

from bot.templates import _parse_sections

_BLACKLIST_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"no visa sponsorship",
    r"will not sponsor",
    r"must be authorized to work",
    r"must be (legally )?authorized",
    r"security clearance required",
    r"local candidates only",
    r"must reside in",
]]

_LEVEL_RE = re.compile(r"\b(senior|mid[\s-]?level|junior|lead|staff)\b", re.IGNORECASE)


def pre_filter(text: str) -> tuple[bool, str | None]:
    """
    Проверяет текст вакансии на blacklist-паттерны.
    text — конкатенация title + description + location.

    Возвращает (blocked, matched_pattern).
    blocked=True означает tier=C без LLM-вызова.
    """
    for pattern in _BLACKLIST_PATTERNS:
        match = pattern.search(text)
        if match:
            return True, match.group(0)
    return False, None


def check_post_completeness(vacancy: dict) -> float:
    """
    Считает насколько хорошо существующий шаблон сможет собрать пост.
    Использует _parse_sections — тот же парсер что и format_global.

    Возвращает float 0.0–1.0. >= 0.8 означает пост достаточно полный.
    """
    found = 0

    if vacancy.get("title"):
        found += 1

    if vacancy.get("location") or vacancy.get("work_format"):
        found += 1

    if vacancy.get("salary_min") or vacancy.get("salary_max"):
        found += 1

    description = vacancy.get("description") or ""

    if _LEVEL_RE.search(description):
        found += 1

    if len(description) > 200:
        sections = _parse_sections(description)
        has_sections = any(k != "__intro__" and sections[k] for k in sections)
        if has_sections:
            found += 1

    return found / 5
