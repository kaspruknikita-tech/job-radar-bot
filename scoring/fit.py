"""
Релевантность вакансии по словарям профиля (profile/profile.py):

    score = title × 2 + плюсы × 0.8 − минусы × 1.5 + опыт + гео

Веса заголовков, стоп-слова, плюс- и минус-сигналы описания и гео-очки — в профиле.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from user_profile import P

logger = logging.getLogger(__name__)

# Стоп-слова заголовка, которые может отменить смежная роль с операционным содержанием
# (правило профиля: sales / account / partner не блокировать, судить по содержанию).
# Уровень и чужие индустрии (junior, стажёр, стройка, склад...) режут всегда.
ADJACENT_OVERRIDABLE_BAD = {"продаж"}

# Опыт из поля hh; noExperience в скане отсекался целиком — здесь сильный минус.
EXPERIENCE_BONUS = {"between3And6": 10, "moreThan6": 8, "between1And3": 0, "noExperience": -20}

# Как RELOC в hh_report.py (оттуда не импортируем: модуль читает файлы при импорте).
RELOCATION_KEYWORDS = ["релокац", "relocation", "помощь с переезд", "оплачиваем переезд", "визов",
                       "work permit", "вид на жительство", "внж", "оформление визы", "переезд за счет",
                       "переезд за счёт", "relocation package"]


@dataclass
class Lexicon:
    title_strong: list[tuple[str, int]] = field(default_factory=list)
    title_bad: list[str] = field(default_factory=list)
    desc_pos: dict[str, int] = field(default_factory=dict)
    desc_neg: dict[str, int] = field(default_factory=dict)

    @property
    def loaded(self) -> bool:
        return bool(self.title_strong)


@dataclass
class FitResult:
    score: float = 0.0
    title_weight: int = 0
    title_bad: str | None = None
    hits: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    geo_points: int = 0
    geo_label: str = ""
    experience_bonus: int = 0
    bonus: float = 0.0   # плюс-сигналы × 0.8
    malus: float = 0.0   # минус-сигналы × 1.5


@lru_cache(maxsize=1)
def load_lexicon() -> Lexicon:
    lexicon = Lexicon(list(P.TITLE_STRONG), list(P.TITLE_BAD), dict(P.DESC_POS), dict(P.DESC_NEG))
    logger.info("Словари профиля: заголовков %d, стоп-слов %d, плюсов %d, минусов %d",
                len(lexicon.title_strong), len(lexicon.title_bad), len(lexicon.desc_pos), len(lexicon.desc_neg))
    return lexicon


def clean(text: str | None) -> str:
    """Без тегов, в нижнем регистре."""
    return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).lower()


def title_weight(name: str, lexicon: Lexicon) -> tuple[int, str | None]:
    """(вес заголовка, сработавшее стоп-слово). Стоп-слово возвращаем, а не обнуляем: решение по смежным ролям — снаружи."""
    n = (name or "").lower()
    bad = next((b for b in lexicon.title_bad if b in n), None)
    flat = re.sub(r"\s+", " ", re.sub(r"\s*[-–—/|]\s*", " ", n))
    best = max((w for key, w in lexicon.title_strong if key in n or key in flat), default=0)
    return best, bad


def geo_points(geo_bucket: str, work_format: str, location: str, blob: str) -> tuple[int, str]:
    g, labels = P.GEO_POINTS, P.GEO_LABELS
    remote = work_format == "Удалёнка" or geo_bucket == "remote_ru"
    hybrid = work_format == "Гибрид"
    relocation = any(k in blob for k in RELOCATION_KEYWORDS)
    russian_city = bool(re.search(r"[а-яё]", location or "", re.I))

    if geo_bucket == "us_only":
        return g["us_only"], "US only"
    if geo_bucket == "other_foreign":
        # Удалёнка с привязкой к чужому региону не лучше офиса за рубежом.
        return g["foreign"] + (g["reloc_package"] if relocation else 0), "зарубеж"
    if geo_bucket == "spb":
        base, label = g["home_city"], labels["home_city"]
    elif geo_bucket == "msk":
        base, label = g["second_city"], labels["second_city"]
    elif geo_bucket == "reloc_georgia_serbia_cyprus":
        base, label = g["reloc"], labels["reloc"]
    elif russian_city:
        base, label = g["region"], "регион РФ"
    else:
        base, label = 0, "гео не указано"

    if remote:
        base, label = max(base, 0) + g["remote"], "удалёнка"
    elif hybrid:
        base += g["hybrid"]
    elif geo_bucket == "msk" and work_format == "Офис":
        base, label = g["second_city_office"], labels["second_city"] + ", офис"
    if relocation and geo_bucket == "reloc_georgia_serbia_cyprus":
        base += g["reloc_package"]
    return base, label


def score(vacancy: dict, geo_bucket: str, lexicon: Lexicon) -> FitResult:
    title = vacancy.get("title") or ""
    blob = clean(f"{title} {vacancy.get('description') or ''}")
    weight, bad = title_weight(title, lexicon)
    hits = [k for k in lexicon.desc_pos if k in blob]
    negatives = [k for k in lexicon.desc_neg if k in blob]
    bonus = sum(lexicon.desc_pos[k] for k in hits)
    malus = sum(lexicon.desc_neg[k] for k in negatives)
    experience = EXPERIENCE_BONUS.get(vacancy.get("experience") or "", 0)
    geo, label = geo_points(geo_bucket, vacancy.get("work_format") or "", vacancy.get("location") or "", blob)
    return FitResult(
        score=round(weight * 2 + bonus * 0.8 - malus * 1.5 + experience + geo, 1),
        title_weight=weight,
        title_bad=bad,
        hits=sorted(hits, key=lambda k: -lexicon.desc_pos[k])[:8],
        negatives=sorted(negatives, key=lambda k: -lexicon.desc_neg[k])[:5],
        geo_points=geo,
        geo_label=label,
        experience_bonus=experience,
        bonus=round(bonus * 0.8, 1),
        malus=round(malus * 1.5, 1),
    )
