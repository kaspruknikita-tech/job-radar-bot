"""
Smoke-тесты: проверяют что основные пути не падают.
Запуск: poetry run python -m pytest tests/smoke_test.py -v
"""
import pytest


# ---------------------------------------------------------------------------
# filters/stopwords
# ---------------------------------------------------------------------------

from filters.stopwords import apply_filters

PASS_CASES = [
    "Project Manager",
    "Технический менеджер проектов",
    "Delivery Manager",
    "Program Manager",
    "Operations Manager",
    "Product Ops Manager",
    "Руководитель проектов (PMO)",
    "Проектный менеджер",
    "Бизнес-аналитик",
    "Партнерский менеджер",
    "Account Manager",
    "Менеджер по внедрению CRM",
    # Ловушки границ слова: короткие стоп-токены не должны их резать
    "Project Manager, Building Operations",
    "Operations Manager, Luxury Retail",
]

BLOCK_CASES = [
    "UX Researcher",
    "UI/UX Designer",
    "Продуктовый дизайнер",
    "Python-разработчик",
    "Веб-разработчик",
    "Аналитик данных",
    "Data Analyst",
    "Системный аналитик",
    "Продуктовый аналитик",
    "HR-менеджер",
    "HR Business Partner",
    "Рекрутер",
    "Копирайтер",
    "SMM-менеджер",
    "Повар",
]


@pytest.mark.parametrize("title", PASS_CASES)
def test_filter_passes(title):
    assert apply_filters({"title": title}), f"Должен пройти: {title!r}"


@pytest.mark.parametrize("title", BLOCK_CASES)
def test_filter_blocks(title):
    assert not apply_filters({"title": title}), f"Должен быть заблокирован: {title!r}"


def test_filter_blocks_german_by_language():
    v = {
        "title": "Projektmanager (m/w/d)",
        "description": "Wir suchen einen erfahrenen Projektmanager für unser Team in Berlin. Sie werden Projekte steuern und Stakeholder koordinieren.",
    }
    assert not apply_filters(v), "Немецкая вакансия должна быть заблокирована по языку"


def test_filter_passes_russian_vacancy():
    v = {
        "title": "Менеджер проектов",
        "description": "Ищем менеджера проектов в команду. Вы будете вести roadmap, координировать разработку и следить за сроками.",
    }
    assert apply_filters(v), "Русская вакансия должна проходить фильтр"


# ---------------------------------------------------------------------------
# parsers/base — make_hash
# ---------------------------------------------------------------------------

from parsers.base import BaseParser


class _DummyParser(BaseParser):
    source_name = "test"
    channel = "global"

    def fetch(self):
        return []


_parser = _DummyParser()


def test_hash_uses_external_id_when_available():
    h1 = _parser.make_hash("Title", "Co", "https://example.com?track=1", external_id="42", source="adzuna")
    h2 = _parser.make_hash("Title", "Co", "https://example.com?track=2", external_id="42", source="adzuna")
    assert h1 == h2, "Хэш должен совпадать при одном external_id, разных URL"


def test_hash_differs_for_different_external_ids():
    h1 = _parser.make_hash("T", "C", "u", external_id="1", source="adzuna")
    h2 = _parser.make_hash("T", "C", "u", external_id="2", source="adzuna")
    assert h1 != h2


def test_hash_fallback_to_url_without_external_id():
    h1 = _parser.make_hash("Title", "Co", "https://a.com")
    h2 = _parser.make_hash("Title", "Co", "https://b.com")
    assert h1 != h2


def test_prepare_adds_required_fields():
    raw = {
        "external_id": "99", "title": "UX Researcher", "company": "Acme",
        "salary_min": None, "salary_max": None, "currency": None,
        "location": "Remote", "work_format": "Remote",
        "url": "https://example.com", "description": "",
    }
    result = _parser.prepare(raw)
    for field in ("hash", "source", "channel", "status", "parsed_at"):
        assert field in result, f"Поле {field!r} отсутствует"
    assert result["source"] == "test"
    assert result["status"] == "new"


# ---------------------------------------------------------------------------
# bot/templates
# ---------------------------------------------------------------------------

from bot.templates import format_ru, format_global, _parse_sections, _format_salary


FULL_DESCRIPTION = """
<p>Ищем UX-исследователя в команду продукта.</p>
<p><strong>Обязанности:</strong></p>
<ul>
<li>Проведение качественных исследований;</li>
<li>Глубинные интервью с пользователями;</li>
<li>Юзабилити-тестирование прототипов;</li>
</ul>
<p><strong>Требования:</strong></p>
<ul>
<li>Опыт в UX-исследованиях от 2 лет;</li>
<li>Знание методов качественных исследований;</li>
</ul>
<p><strong>Условия:</strong></p>
<ul>
<li>Удалённая работа;</li>
<li>ДМС после испытательного срока;</li>
</ul>
"""

ALT_DESCRIPTION = """
<p>Молодое агентство ищет исследователя.</p>
<p><strong>Что нужно будет делать:</strong></p>
<ul><li>Проводить интервью;</li><li>Анализировать данные;</li></ul>
<strong>Что для нас важно:</strong>
<ul><li>Опыт от 1 года;</li><li>Внимание к деталям;</li></ul>
<p><strong>Работа с нами — это:</strong></p>
<ul><li>Официальное трудоустройство;</li><li>Гибкий график;</li></ul>
"""

BASE_VACANCY = {
    "title": "UX-исследователь", "company": "Яндекс",
    "location": "Москва", "work_format": "Удалёнка",
    "salary_min": 120000, "salary_max": 180000, "currency": "RUB",
    "url": "https://hh.ru/vacancy/1", "snippet": "",
}


def _v(**kwargs):
    return {**BASE_VACANCY, **kwargs}


def test_format_ru_full_structure():
    post = format_ru(_v(description=FULL_DESCRIPTION))
    assert "О роли" in post
    assert "Задачи" in post
    assert "Требования" in post
    assert "Условия" in post
    assert "Откликнуться на hh.ru" in post


def test_format_ru_alt_keywords():
    post = format_ru(_v(description=ALT_DESCRIPTION))
    assert "Задачи" in post
    assert "Требования" in post
    assert "Условия" in post


def test_format_ru_plain_text():
    plain = "<p>We are looking for a researcher to join our team and conduct user studies.</p>"
    post = format_ru(_v(description=plain))
    assert "О роли" in post
    assert "Откликнуться" in post


def test_format_ru_no_description_uses_snippet():
    post = format_ru(_v(description="", snippet="Short snippet about the role."))
    assert "Short snippet" in post


def test_format_ru_salary_shown():
    post = format_ru(_v(description=""))
    assert "120 000" in post
    assert "₽" in post


def test_format_ru_no_salary_no_money_line():
    post = format_ru(_v(description="", salary_min=None, salary_max=None))
    assert "💰" not in post


def test_format_global():
    post = format_global(_v(description=FULL_DESCRIPTION, channel="global"))
    assert "Responsibilities" in post
    assert "Requirements" in post
    assert "Apply" in post


def test_format_escapes_html():
    post = format_ru(_v(title="<script>alert(1)</script>", description=""))
    assert "<script>" not in post


# ---------------------------------------------------------------------------
# _parse_sections
# ---------------------------------------------------------------------------

def test_parse_sections_standard():
    sections = _parse_sections(FULL_DESCRIPTION)
    assert "__intro__" in sections
    assert any("обязанност" in k.lower() for k in sections)


def test_parse_sections_alt_keywords():
    sections = _parse_sections(ALT_DESCRIPTION)
    assert "Что нужно будет делать" in sections
    assert "Что для нас важно" in sections


def test_parse_sections_bare_strong_header():
    html = "<p>Intro.</p><strong>Раздел:</strong><ul><li>item</li></ul>"
    sections = _parse_sections(html)
    assert "Раздел" in sections
    assert sections["Раздел"] == ["item"]


def test_parse_sections_plain_text_fallback():
    sections = _parse_sections("<p>Just plain text without any structure here.</p>")
    assert "__intro__" in sections
    assert isinstance(sections["__intro__"], str)


def test_parse_sections_empty():
    assert _parse_sections("") == {}
    assert _parse_sections(None) == {}


# ---------------------------------------------------------------------------
# _format_salary
# ---------------------------------------------------------------------------

def test_salary_range():
    v = {"salary_min": 100000, "salary_max": 200000, "currency": "RUB"}
    assert "100 000" in _format_salary(v)
    assert "200 000" in _format_salary(v)
    assert "₽" in _format_salary(v)


def test_salary_min_only():
    result = _format_salary({"salary_min": 80000, "salary_max": None, "currency": "USD"})
    assert "от" in result
    assert "$" in result


def test_salary_max_only():
    result = _format_salary({"salary_min": None, "salary_max": 150000, "currency": "EUR"})
    assert "до" in result
    assert "€" in result


def test_salary_none():
    assert _format_salary({"salary_min": None, "salary_max": None, "currency": None}) is None


# ---------------------------------------------------------------------------
# database — мокаем psycopg2, проверяем логику функций
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch
import database


def _make_conn(fetchone_result=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_vacancy_exists_true():
    conn, cur = _make_conn(fetchone_result=(1,))
    with patch("database._get_connection", return_value=conn):
        assert database.vacancy_exists("somehash") is True


def test_vacancy_exists_false():
    conn, cur = _make_conn(fetchone_result=None)
    with patch("database._get_connection", return_value=conn):
        assert database.vacancy_exists("somehash") is False


def test_vacancy_exists_by_external_true():
    conn, cur = _make_conn(fetchone_result=(1,))
    with patch("database._get_connection", return_value=conn):
        assert database.vacancy_exists_by_external("42", "adzuna") is True


def test_vacancy_exists_by_external_false():
    conn, cur = _make_conn(fetchone_result=None)
    with patch("database._get_connection", return_value=conn):
        assert database.vacancy_exists_by_external("42", "adzuna") is False


def test_insert_vacancy_returns_id():
    conn, cur = _make_conn(fetchone_result=(7,))
    with patch("database._get_connection", return_value=conn):
        v = {
            "external_id": "1", "source": "hh.ru", "title": "UX Researcher",
            "company": "Co", "salary_min": None, "salary_max": None, "currency": None,
            "location": "Moscow", "work_format": "Remote", "url": "https://hh.ru/1",
            "description": "", "snippet": None,
            "hash": "abc", "status": "new", "channel": "ru",
            "parsed_at": "2026-01-01T00:00:00+00:00",
        }
        result = database.insert_vacancy(v)
        assert result == 7


def test_insert_vacancy_duplicate_returns_none():
    import psycopg2
    conn, cur = _make_conn()
    cur.execute.side_effect = psycopg2.errors.UniqueViolation
    with patch("database._get_connection", return_value=conn):
        v = {
            "external_id": "1", "source": "hh.ru", "title": "UX Researcher",
            "company": "Co", "salary_min": None, "salary_max": None, "currency": None,
            "location": "Moscow", "work_format": "Remote", "url": "https://hh.ru/1",
            "description": "", "snippet": None,
            "hash": "abc", "status": "new", "channel": "ru",
            "parsed_at": "2026-01-01T00:00:00+00:00",
        }
        result = database.insert_vacancy(v)
        assert result is None


def test_get_setting_returns_value():
    conn, cur = _make_conn(fetchone_result=("myvalue",))
    with patch("database._get_connection", return_value=conn):
        result = database.get_setting("mykey")
        assert result == "myvalue"


def test_get_setting_returns_none_when_missing():
    conn, cur = _make_conn(fetchone_result=None)
    with patch("database._get_connection", return_value=conn):
        result = database.get_setting("missing_key")
        assert result is None
