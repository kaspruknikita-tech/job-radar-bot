"""Telegram через публичные превью t.me/s/: разбор страницы, заголовки, отсечки. Без сети."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from parsers import telegram_preview as tp
from parsers.telegram import TelegramChannelParser, vacancy_title

NOW = datetime.now(timezone.utc)


def _post(pid, when, body):
    return (f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="igaming_work/{pid}">'
            f'<div class="tgme_widget_message_text js-message_text">{body}</div>'
            f'<a class="tgme_widget_message_date" href="https://t.me/igaming_work/{pid}">'
            f'<time datetime="{when.isoformat()}"></time></a></div></div>')


VACANCY = ("#вакансия #remote<br/>🔥 <b>Affiliate Manager</b> в iGaming<br/>Удалённо, 2000–3000 $<br/>"
           "Ведение партнёров, отчётность, CPA-сети, работа с трафиком и аналитикой.")
RESUME = "#резюме<br/>Ищу работу Project Manager, опыт 5 лет, удалённо, рассмотрю предложения от компаний."


def _page(*posts):
    return "<html><body>" + "".join(posts) + "</body></html>"


@pytest.fixture
def channels(monkeypatch):
    monkeypatch.setattr(tp.config, "TG_SOURCE_CHANNELS", ["igaming_work"])
    monkeypatch.setattr(tp.config, "TG_API_ID", 0)
    monkeypatch.setattr(tp.config, "TG_API_HASH", "")
    monkeypatch.setattr(tp.config, "TG_SESSION_STRING", "")
    monkeypatch.setattr(tp.config, "TG_DAYS_BACK", 7)
    monkeypatch.setattr(tp.time, "sleep", lambda s: None)


def _response(status, html=""):
    r = MagicMock(); r.status_code = status; r.text = html
    return r


def test_parse_page_keeps_line_breaks_and_dates():
    posts = tp.parse_page(_page(_post(101, NOW, VACANCY)))
    assert posts[0]["id"] == 101 and posts[0]["date"].tzinfo
    assert "🔥 Affiliate Manager в iGaming" in posts[0]["text"].splitlines()


@pytest.mark.parametrize("text,expected", [
    ("#job #remote\n🔥 Мы растём!\nИщем Project Manager в команду", "Ищем Project Manager в команду"),
    ("🚀 Delivery Lead (iGaming)\nУдалённо", "Delivery Lead (iGaming)"),
    ("#вакансия\nКомпания ищет дизайнера интерфейсов", "Компания ищет дизайнера интерфейсов"),
])
def test_vacancy_title(text, expected):
    assert vacancy_title(text) == expected


def test_fetch_builds_vacancy_and_stops_at_old_posts(channels):
    html = _page(_post(99, NOW - timedelta(days=10), VACANCY), _post(100, NOW, RESUME), _post(101, NOW, VACANCY))
    with patch.object(tp.requests, "get", return_value=_response(200, html)) as get:
        vacancies = tp.TelegramPreviewParser().fetch()
    assert get.call_count == 1
    assert len(vacancies) == 1
    v = vacancies[0]
    assert v["external_id"] == "igaming_work_101" and v["url"] == "https://t.me/igaming_work/101"
    assert v["title"] == "Affiliate Manager в iGaming"
    assert v["work_format"] == "Удалёнка"
    assert (v["salary_min"], v["salary_max"], v["currency"]) == (2000, 3000, "USD")
    assert v["published_at"]


def test_closed_preview_is_skipped(channels):
    with patch.object(tp.requests, "get", return_value=_response(302)):
        assert tp.TelegramPreviewParser().fetch() == []


def test_telethon_keys_turn_preview_off(channels, monkeypatch):
    monkeypatch.setattr(tp.config, "TG_API_ID", 12345)
    monkeypatch.setattr(tp.config, "TG_API_HASH", "hash")
    monkeypatch.setattr(tp.config, "TG_SESSION_STRING", "session")
    with patch.object(tp.requests, "get") as get:
        assert tp.TelegramPreviewParser().fetch() == []
        get.assert_not_called()


def test_same_hash_as_telethon_parser():
    raw = {"external_id": "igaming_work_101", "title": "t", "company": "", "url": "u"}
    assert tp.TelegramPreviewParser().prepare(raw)["hash"] == TelegramChannelParser().prepare(raw)["hash"]
