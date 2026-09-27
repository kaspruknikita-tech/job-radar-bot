"""
Скоринг без LLM: pre_filter, пороги тиров и score_vacancy целиком.
Карьерная OS и словари профиля подменяются игрушечными — тесты не зависят
от файлов вне репозитория и не ходят в сеть.
"""
import importlib

import pytest

import scoring
from scoring import score_vacancy
from scoring.career_os import Block, CareerIndex
from scoring.fit import Lexicon
from scoring.pre_filter import check_post_completeness, pre_filter
from scoring.tier_mapper import map_tier


_FULL_DESCRIPTION = """
<h2>About the role</h2>
<p>We are looking for a Senior UX Researcher.</p>
<h2>Responsibilities</h2>
<ul><li>Run user interviews</li><li>Mixed methods research</li></ul>
<h2>Requirements</h2>
<ul><li>5+ years experience</li><li>Senior level expertise</li></ul>
"""
_SPARSE_DESCRIPTION = "We need someone. Apply now."


# ---------------------------------------------------------------------------
# pre_filter (перенесено без изменений)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_blocked", [
    ("no visa sponsorship available for this role", True),
    ("We will not sponsor visas", True),
    ("You must be authorized to work in the US", True),
    ("must be legally authorized to work", True),
    ("security clearance required for this position", True),
    ("local candidates only please", True),
    ("candidates must reside in the United States", True),
    ("We welcome remote workers from anywhere", False),
    ("Visa sponsorship is available", False),
    ("Open to candidates worldwide", False),
])
def test_pre_filter_blacklist(text, expected_blocked):
    blocked, matched = pre_filter(text)
    assert blocked == expected_blocked, f"text={text!r}, matched={matched!r}"


def test_completeness_full_vacancy():
    vacancy = {
        "title": "Senior UX Researcher",
        "company": "Figma",
        "location": "Remote",
        "work_format": "remote",
        "salary_min": 90000,
        "salary_max": 130000,
        "description": _FULL_DESCRIPTION,
    }
    score = check_post_completeness(vacancy)
    assert score >= 0.8, f"Ожидали >= 0.8, получили {score}"


def test_completeness_sparse_vacancy():
    vacancy = {
        "title": "UX Researcher",
        "description": _SPARSE_DESCRIPTION,
    }
    score = check_post_completeness(vacancy)
    assert score < 0.8, f"Ожидали < 0.8, получили {score}"


def test_completeness_no_location_no_salary():
    vacancy = {
        "title": "UX Researcher",
        "description": _FULL_DESCRIPTION,
    }
    score = check_post_completeness(vacancy)
    assert 0.0 < score < 1.0




# ---------------------------------------------------------------------------
# Пороги тиров
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (200, "S"), (130, "S"), (129, "A"), (95, "A"), (94, "B"), (65, "B"), (64, "C"), (-50, "C"),
])
def test_tier_thresholds(score, expected):
    assert map_tier(score)[0] == expected


def test_tier_actions():
    assert map_tier(130) == ("S", "curated_plus")
    assert map_tier(95) == ("A", "curated")
    assert map_tier(65) == ("B", "main")
    assert map_tier(0) == ("C", "skip")


def test_llm_modules_are_gone():
    for name in ("scoring.llm_scorer", "scoring.brand_scorer", "scoring.validator", "scoring.score_combiner"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


# ---------------------------------------------------------------------------
# score_vacancy
# ---------------------------------------------------------------------------

@pytest.fixture
def offline(monkeypatch):
    index = CareerIndex(blocks=[Block(
        id="nex-integrations", archetypes=["TPM"], company="Nexters",
        tags=["API", "Jira", "SLA"], text="интеграции по api, jira, sla с вендорами",
    )])
    lexicon = Lexicon(
        title_strong=[("technical project manager", 45), ("project manager", 32)],
        title_bad=["продаж", "junior", "строитель"],
        desc_pos={"api": 8, "sla": 8, "igaming": 14},
        desc_neg={"холодные звонк": 16},
    )
    monkeypatch.setattr(scoring, "_career_index", lambda: index)
    monkeypatch.setattr(scoring, "_lexicon", lambda: lexicon)
    monkeypatch.setattr(scoring, "visa_lookup", None)


def _vacancy(**overrides):
    base = {"id": 1, "title": "", "company": "Acme", "description": "",
            "location": "Москва", "work_format": "Удалёнка",
            "salary_min": None, "salary_max": None, "currency": None}
    base.update(overrides)
    return base


REQUIREMENTS = ("<p><b>Требования</b></p><ul><li>Интеграции по API</li>"
                "<li>Понимание SLA</li><li>Опыт с Jira</li></ul><p>Продукт в iGaming</p>")


def test_strong_remote_tpm_lands_on_top(offline):
    r = score_vacancy(_vacancy(title="Technical Project Manager", description=REQUIREMENTS,
                               experience="between3And6"))
    assert r.tier == "S"
    assert r.archetype == "TPM" and r.geo_bucket == "remote_ru"
    assert r.ats_score >= 80 and r.ats_details["matched"]
    assert "ATS" in r.reason and "удалёнка" in r.reason
    assert r.score_breakdown["заголовок"] == 90


def test_seniority_stop_word_always_blocks(offline):
    r = score_vacancy(_vacancy(title="Junior Project Manager", description=REQUIREMENTS))
    assert r.tier == "C" and "Стоп-слово" in r.reason


def test_sales_with_operational_content_is_not_blocked(offline):
    r = score_vacancy(_vacancy(title="Менеджер по продажам",
                               description="Ведение партнёрских программ, отчётность, интеграции по API"))
    assert "Стоп-слово" not in r.reason


def test_cold_sales_is_blocked(offline):
    r = score_vacancy(_vacancy(title="Менеджер по продажам", description="Холодные звонки по базе клиентов"))
    assert r.tier == "C" and "Стоп-слово" in r.reason


def test_region_office_scores_low(offline):
    r = score_vacancy(_vacancy(title="Project Manager", location="Казань", work_format="Офис"))
    assert r.tier == "C"
    assert r.score_breakdown["гео"] == -25


def test_unknown_title_with_archetype_gets_floor(offline):
    r = score_vacancy(_vacancy(title="Enablement Manager"))
    assert r.archetype == "PERF"
    assert r.score_breakdown["архетип_вне_словаря"] == 44


def test_us_authorization_is_prefiltered(offline):
    r = score_vacancy(_vacancy(title="Project Manager",
                               description="You must be authorized to work in the United States"))
    assert r.pre_filter_blocked and r.tier == "C"


def test_english_c1_is_penalized(offline):
    r = score_vacancy(_vacancy(title="Project Manager", description="Fluent English is required"))
    assert r.score_breakdown.get("английский_c1") == -15


@pytest.mark.parametrize("title", [
    "QA тестировщик со знанием платформы ЦФТ / Проектная работа",
    "QA Delivery Lead", "Старший инженер по тестированию", "AQA Engineer (Flutter)",
])
def test_qa_titles_are_stop_roles(offline, title):
    r = score_vacancy(_vacancy(title=title, description=REQUIREMENTS))
    assert r.tier == "C" and "Стоп-слово" in r.reason


def test_qatar_is_not_qa(offline):
    from filters.stopwords import stop_role
    assert stop_role("Project Manager, Qatar office") is None


def test_own_base_as_requirement_is_penalized(offline):
    text = ("<p>Ключевая задача — масштабировать направление за счёт собственной базы партнёров.</p>"
            "<p>Подключение веб-мастеров, в том числе из собственной базы.</p>")
    r = score_vacancy(_vacancy(title="Affiliate Manager", description=text))
    assert r.score_breakdown.get("своя_база") == -40
    assert r.tier == "C" and "своя база" in r.reason


def test_own_base_as_nice_to_have_is_not_penalized(offline):
    text = "<p>Будет преимуществом: собственная база контактов вебмастеров.</p>"
    r = score_vacancy(_vacancy(title="Affiliate Manager", description=text))
    assert "своя_база" not in r.score_breakdown


def test_moscow_hybrid_is_below_remote(offline):
    remote = score_vacancy(_vacancy(title="Project Manager", work_format="Удалёнка"))
    hybrid = score_vacancy(_vacancy(title="Project Manager", work_format="Гибрид"))
    assert hybrid.score_breakdown["гео"] == -6
    assert hybrid.score < remote.score


def test_moscow_office_is_minus_40(offline):
    office = score_vacancy(_vacancy(title="Project Manager", work_format="Офис"))
    assert office.score_breakdown["гео"] == -40

