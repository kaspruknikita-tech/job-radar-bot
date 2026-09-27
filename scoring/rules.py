"""
Поля вакансии без LLM: архетип, гео, английский, домен, операционное содержание.

Правила выведены из профиля (core.md) и сверены с разметкой LLM на 769 вакансиях
(см. историю перехода на кодовый скоринг). Структурные поля источника — формат
работы и город — надёжнее текста, поэтому идут первыми.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from user_profile import P

_I = re.I


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), _I)


# Архетипы, домен и города — из profile/profile.py. Порядок архетипов важен: от узких к широкому.
_ARCHETYPES = [(name, _rx(*parts)) for name, parts in P.ARCHETYPES]
_ADJACENT_ROLE = _rx(*P.ADJACENT_ROLE)
_OPS_CONTENT = _rx(*P.OPS_CONTENT)
_COLD_SALES = _rx(*P.COLD_SALES)
_DOMAIN = _rx(*P.DOMAIN)
_EN_C1 = _rx(r"\bc1\b", r"\bc2\b", r"advanced english", r"fluent", r"свободн\w* (владение )?английск", r"native")
_EN_B2 = _rx(r"\bb2\b", r"upper.?intermediate", r"\bintermediate\b",
             r"английск\w* (на уровне )?(чтени|технич|разговорн)")
_RELOC_COUNTRY = _rx(*P.RELOC_COUNTRIES)
_US_ONLY = _rx(r"united states", r"\busa\b", r"\bus only\b", r"authorized to work in the u")
_RELOCATION = _rx(r"релокац", r"relocation")
_VISA = _rx(r"visa sponsor", r"визов\w* поддержк")
_SENIOR = _rx(r"senior", r"\blead\b", r"старш", r"ведущ", r"head of", r"руководител",
              r"опыт (работы )?от [3-9]", r"[3-9]\+? (лет|years)")
_JUNIOR = _rx(r"junior", r"стаж[её]р", r"\bintern", r"без опыта", r"начинающ")
# Основной и второй город (бакеты spb / msk): основы слов, чтобы ловить падежи.
_SPB = _rx(*P.HOME_CITY)
_MSK = _rx(*P.SECOND_CITY)
_REMOTE_ANYWHERE = _rx(r"worldwide", r"anywhere", r"\bglobal\b", r"по всему миру", r"из любой")
_RUSSIA = _rx(r"росси", r"russia", r"\bрф\b")


def plain_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def archetype(title: str, text: str) -> tuple[str, bool]:
    """(архетип, смежная_роль). Смежные роли (продажи, партнёры, аккаунты, BA)
    получают OPS только при операционном содержании, без холодных продаж."""
    arch = next((name for name, rx in _ARCHETYPES if rx.search(title)), "none")
    adjacent = bool(_ADJACENT_ROLE.search(title))
    if arch == "none" and adjacent and not _COLD_SALES.search(text) and (
            _OPS_CONTENT.search(text) or re.search(r"партн[её]р|partner|affiliate", title, _I)):
        arch = "OPS"
    return arch, adjacent


# Формат работы из текста — для источников, которые не отдают его полем (rabota.ru, yandex, борды).
_REMOTE_TEXT = _rx(r"удал[её]нн", r"удал[её]нк", r"\bremote\b", r"дистанционн", r"из любой точки", r"work from anywhere")
_HYBRID_TEXT = _rx(r"гибрид", r"\bhybrid\b")
_NO_REMOTE = _rx(r"(не|без|no|not|non)[\s-]+(\w+[\s-]+)?(удал|remote|дистанц)", r"удал[её]нн\w* (работа )?не рассматрива")


def work_format_from_text(text: str) -> str:
    head = text[:1500]
    if _REMOTE_TEXT.search(head) and not _NO_REMOTE.search(head):
        return "Удалёнка"
    if _HYBRID_TEXT.search(head):
        return "Гибрид"
    return ""


def geo(location: str, work_format: str, text: str) -> tuple[str, str]:
    """(geo_bucket, remote_policy) по правилам профиля."""
    loc = location or ""
    if not work_format:
        work_format = work_format_from_text(f"{loc} {text}")
    head = f"{loc} {text[:600]}"
    remote = work_format == "Удалёнка" or bool(re.search(r"\bremote\b", loc, _I))
    policy = {"Удалёнка": "global", "Гибрид": "hybrid", "Офис": "on_site"}.get(work_format or "", "unclear")

    if _RELOC_COUNTRY.search(head):
        return "reloc_georgia_serbia_cyprus", policy
    if _US_ONLY.search(f"{loc} {text}"):
        return "us_only", "us_only"
    latin_location = bool(loc.strip()) and not re.search(r"[а-яё]", loc, _I)
    if remote:
        bare = loc.strip().lower() in ("", "remote")
        if latin_location and not bare and not _REMOTE_ANYWHERE.search(loc) and not _RUSSIA.search(loc):
            return "other_foreign", "eu"  # удалёнка с привязкой к региону
        return "remote_ru", "global"
    if _SPB.search(head):
        return "spb", policy
    if _MSK.search(head):
        return "msk", policy
    if latin_location:
        return "other_foreign", policy
    return "unclear", policy


def english_level(text: str) -> str:
    if _EN_C1.search(text):
        return "c1_plus"
    if _EN_B2.search(text):
        return "b2_ok"
    cyrillic = len(re.findall(r"[а-яё]", text, _I)) / max(len(text), 1)
    if cyrillic > 0.3 and not re.search(r"английск|english", text, _I):
        return "b2_ok"  # русскоязычная вакансия без требования к языку
    return "unclear"


def extract(vacancy: dict) -> dict:
    title = vacancy.get("title") or ""
    text = plain_text(vacancy.get("description"))
    blob = f"{title} {vacancy.get('company') or ''} {text}"
    arch, adjacent = archetype(title, text)
    geo_bucket, remote_policy = geo(vacancy.get("location") or "", vacancy.get("work_format") or "", text)
    if _SENIOR.search(f"{title} {text}"):
        level = "senior"
    elif _JUNIOR.search(f"{title} {text}"):
        level = "junior"
    else:
        level = "unclear"
    return {
        "archetype": arch,
        "adjacent_role": adjacent,
        "ops_content": bool(_OPS_CONTENT.search(text)) and not _COLD_SALES.search(text),
        "domain_match": bool(_DOMAIN.search(blob)),
        "geo_bucket": geo_bucket,
        "remote_policy": remote_policy,
        "english_level_required": english_level(text),
        "visa_sponsorship": "yes" if _VISA.search(text) else "unclear",
        "relocation_support": "yes" if _RELOCATION.search(text) else "unclear",
        "experience_level": level,
    }
