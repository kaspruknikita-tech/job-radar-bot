from __future__ import annotations

_ACTIONS: dict[str, str] = {
    "S": "curated_plus",
    "A": "curated",
    "B": "main",
    "C": "skip",
}

# Итоговый скор = релевантность по правилам профиля (заголовок, сигналы, опыт, гео)
# + ATS-совпадение с карьерной OS. Пороги откалиброваны на 769 вакансиях и 20 реальных
# откликах: в S/A около 30% базы, все отклики попадают в S/A.
_THRESHOLDS: list[tuple[float, str]] = [
    (130, "S"),
    (95, "A"),
    (65, "B"),
    (float("-inf"), "C"),
]


def map_tier(score: float) -> tuple[str, str]:
    for min_score, tier in _THRESHOLDS:
        if score >= min_score:
            return tier, _ACTIONS[tier]
    return "C", _ACTIONS["C"]
