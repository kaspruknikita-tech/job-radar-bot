"""
Кодовый скоринг без LLM: правила извлечения полей и ATS-совпадение с карьерной OS.
Карьерная OS здесь игрушечная — тесты не зависят от реальных файлов вне репозитория.
"""
import pytest

from scoring import rules
from scoring.ats import match
from scoring.career_os import Block, CareerIndex, Gap


@pytest.fixture
def index():
    return CareerIndex(
        blocks=[
            Block(id="nex-integrations", archetypes=["TPM"], company="Nexters",
                  tags=["API", "AppsFlyer", "integration"],
                  text="настроил интеграции по api с appsflyer, согласовал sla с вендором"),
            Block(id="nex-jira-ops", archetypes=["DEL"], company="Nexters",
                  tags=["Jira", "SLA-triggers", "PostgreSQL"],
                  text="сквозной workflow в jira, дашборды, sla-триггеры"),
        ],
        gaps=[
            Gap(topic="Adjust (MMP)", status="no-exp"),
            Gap(topic="PostgreSQL hands-on", status="no-exp"),
            Gap(topic="Tableau hands-on", status="unformed"),
        ],
        domains=["GameDev (mobile F2P)"],
        honest_gaps=["Нет hands-on Terraform / Ansible / Kubernetes"],
    )


def _vacancy(title, requirements, extra=""):
    items = "".join(f"<li>{r}</li>" for r in requirements)
    return {"title": title, "description": f"<p><b>Требования</b></p><ul>{items}</ul>{extra}"}


# --- rules: гео ---

@pytest.mark.parametrize("location,work_format,text,expected", [
    ("Москва", "Удалёнка", "", "remote_ru"),
    ("Санкт-Петербург", "Гибрид", "", "spb"),
    ("Москва", "Офис", "", "msk"),
    ("Germany", "Удалёнка", "", "other_foreign"),
    ("Remote", "Удалёнка", "", "remote_ru"),
    ("", "", "Office based in Limassol, Cyprus", "reloc_georgia_serbia_cyprus"),
    ("United States", "", "", "us_only"),
    ("Казань", "Офис", "", "unclear"),
])
def test_geo_bucket(location, work_format, text, expected):
    assert rules.geo(location, work_format, text)[0] == expected


def test_office_outside_target_cities_is_on_site():
    assert rules.geo("Казань", "Офис", "")[1] == "on_site"


# --- rules: английский ---

@pytest.mark.parametrize("text,expected", [
    ("Требуется английский на уровне C1 для переговоров", "c1_plus"),
    ("Fluent English is required", "c1_plus"),
    ("Английский B2 для чтения документации", "b2_ok"),
    ("Ищем менеджера проектов в команду, работа с подрядчиками и сроками", "b2_ok"),
    ("We are looking for a project manager to run delivery", "unclear"),
])
def test_english_level(text, expected):
    assert rules.english_level(text) == expected


# --- rules: архетип ---

@pytest.mark.parametrize("title,text,expected", [
    ("Technical Project Manager", "", "TPM"),
    ("Менеджер по работе с проектами", "", "DEL"),
    ("Product Operations Lead", "", "OPS"),
    ("Руководитель PMO", "", "TRANS"),
    ("Менеджер по продажам", "холодные звонки по базе, работа с возражениями", "none"),
    ("Affiliate Manager", "ведение партнёрских программ, отчётность по трафику", "OPS"),
])
def test_archetype(title, text, expected):
    assert rules.archetype(title, text)[0] == expected


def test_extract_has_all_combiner_fields():
    fields = rules.extract({"title": "Delivery Manager", "description": "<p>Удалённо</p>",
                            "location": "Москва", "work_format": "Удалёнка"})
    for key in ("archetype", "adjacent_role", "ops_content", "domain_match", "geo_bucket",
                "remote_policy", "english_level_required", "visa_sponsorship",
                "relocation_support", "experience_level"):
        assert key in fields


# --- ATS ---

def test_direct_experience_scores_high(index):
    res = match(_vacancy("Technical Project Manager",
                         ["Опыт работы с Jira", "Понимание SLA", "Интеграции по API"]), index)
    assert res.score >= 85
    assert {"jira", "sla", "api"} <= {m.lower() for m in res.matched}
    assert "nex-jira-ops" in res.blocks or "nex-integrations" in res.blocks


def test_same_class_tool_is_transferable(index):
    res = match(_vacancy("Project Manager", ["Опыт с YouTrack", "Опыт с Redmine", "Знание Trello"]), index)
    assert "youtrack" in res.transferable
    assert 70 <= res.score < 90


def test_no_exp_gap_is_reported(index):
    res = match(_vacancy("MarTech Manager", ["Настройка Adjust", "Работа с Adjust SDK", "Опыт с Jira"]), index)
    assert any(g.lower() == "adjust" for g in res.gaps)


def test_experience_in_blocks_overrides_gap_topic(index):
    res = match(_vacancy("Data PM", ["PostgreSQL", "Jira", "API"]), index)
    assert not any(g.lower() == "postgresql" for g in res.gaps)


def test_foreign_requirements_pull_score_down(index):
    res = match(_vacancy("Менеджер по продажам",
                         ["Холодные звонки по базе", "Работа с возражениями", "Выполнение плана продаж"]), index)
    assert res.score < 50
    assert "холодные продажи" in res.gaps


def test_commission_pay_counts_even_in_conditions(index):
    vacancy = _vacancy("Менеджер", ["Опыт с Jira", "Понимание SLA", "Интеграции по API"],
                       extra="<p><b>Условия</b></p><ul><li>Доход без потолка, процент от продаж</li></ul>")
    assert "сдельная оплата" in match(vacancy, index).gaps


def test_empty_index_disables_ats():
    res = match(_vacancy("Project Manager", ["Jira"]), CareerIndex())
    assert res.score == 0 and res.low_info


def test_multiword_terms_match():
    index = CareerIndex(blocks=[Block(id="nda-bi", archetypes=["TPM"], company="NDA", tags=["Power BI"],
                                      text="строил отчётность в power bi, считал lead time")])
    res = match(_vacancy("BI Project Manager", ["Опыт с Power BI", "Контроль lead time", "Power BI дашборды"]), index)
    assert "power bi" in [m.lower() for m in res.matched]


def test_partial_market_signal_is_transferable(index):
    index.market_signals = [("Confluence (база знаний, шаблоны)", "частично")]
    res = match(_vacancy("Project Manager", ["Ведение Confluence", "Шаблоны в Confluence", "Опыт с Jira"]), index)
    assert "confluence" in res.transferable


def test_market_signal_without_experience_is_gap(index):
    index.market_signals = [("Zoho (CRM, automation, Analytics)", "нет")]
    res = match(_vacancy("Ops Manager", ["Настройка Zoho", "Автоматизации в Zoho", "Опыт с Jira"]), index)
    assert "Zoho" in res.gaps


@pytest.mark.parametrize("text,expected", [
    ("Формат работы: удалённо, по всей России", "remote_ru"),
    ("Полностью удаленная работа, гибкий график", "remote_ru"),
    ("Работаем только в офисе, удалённая работа не рассматривается", "unclear"),
    ("Формат — гибрид, офис в Москве", "msk"),
])
def test_geo_reads_work_format_from_text_when_field_missing(text, expected):
    assert rules.geo("", "", text)[0] == expected


def test_structured_work_format_wins_over_text():
    assert rules.geo("Москва", "Офис", "раньше работали удалённо")[0] == "msk"


@pytest.mark.parametrize("text,expected", [
    ("Офис в Москве, м. Белорусская", "msk"),
    ("Работа в офисе в Петербурге", "spb"),
])
def test_geo_city_in_any_case(text, expected):
    assert rules.geo("", "Офис", text)[0] == expected

