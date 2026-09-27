"""
Решения по вакансиям из Telegram и Google-таблица.
Сеть не трогаем: таблица проверяется на чистых функциях, отправка — на заглушках.
Статусы в БД проверяются на локальной Postgres, если она доступна.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from bot import moderator
from exporters import sheets


# --- кнопки ---

def _all_buttons(keyboard):
    return [btn for row in keyboard["inline_keyboard"] for btn in row]


def test_card_keyboard_has_decision_buttons():
    buttons = _all_buttons(moderator._keyboard(123))
    data = [b["callback_data"] for b in buttons]
    assert "apply:123" in data and "decline:123" in data
    assert {"later:123:180", "later:123:1440"} <= set(data)
    assert not any(d.startswith(("approve", "schedule")) for d in data)


def test_decline_keyboard_offers_all_reasons_and_back():
    data = [b["callback_data"] for b in _all_buttons(moderator._decline_keyboard(7))]
    for code in moderator.DECLINE_REASONS:
        assert f"reason:7:{code}" in data
    assert "back:7" in data


def test_callback_data_fits_telegram_limit():
    big_id = 2**31 - 1
    for kb in (moderator._keyboard(big_id), moderator._decline_keyboard(big_id)):
        for btn in _all_buttons(kb):
            assert len(btn["callback_data"].encode()) <= 64


# --- таблица: строки и возвраты ---

VACANCY = {"id": 42, "title": "Delivery Manager", "company": "Acme", "salary_min": 200000,
           "salary_max": None, "currency": "RUR", "work_format": "Удалёнка", "location": "Москва",
           "source": "hh.ru", "url": "https://hh.ru/vacancy/42", "published_at": "2026-09-14T10:00:00",
           "parsed_at": "2026-09-15T08:00:00"}
SCORING = {"tier": "A", "score": 120, "ats_score": 88, "archetype": "DEL", "geo_bucket": "remote_ru",
           "reason": "ATS 88% · совпало: jira"}


def test_vacancy_row_follows_sheet_headers():
    headers = ["Ссылка", "ID", "Решение", "Причина", "Тир", "ATS"]
    row = sheets.vacancy_row(VACANCY, SCORING, headers, decision="Не подходит", reason="гео")
    assert row == ["https://hh.ru/vacancy/42", 42, "Не подходит", "гео", "A", 88]


def test_rejected_row_keeps_bot_reason():
    row = sheets.rejected_row(VACANCY, SCORING, "Стоп-слово в заголовке: «продаж»", sheets.REJECTED_HEADERS)
    assert row[sheets.REJECTED_HEADERS.index("Причина отказа бота")] == "Стоп-слово в заголовке: «продаж»"
    assert row[sheets.REJECTED_HEADERS.index("Вернуть")] == ""


def test_returns_parse_marks_and_ignores_unchecked_boxes():
    headers = sheets.REJECTED_HEADERS
    def row(vid, back="", returned=""):
        r = [""] * len(headers)
        r[headers.index("ID")], r[headers.index("Вернуть")], r[headers.index("Возвращена")] = str(vid), back, returned
        return r
    values = [headers, row(1, "да"), row(2, "FALSE"), row(3, "TRUE"), row(4, "да", "15.09.2026 10:00"), row(5, "")]
    ids, rows = sheets.returns_from_values(values)
    assert ids == [1, 3]
    assert rows == [2, 4]


def test_sheets_disabled_without_id(monkeypatch):
    monkeypatch.setattr(sheets.config, "GOOGLE_SHEET_ID", "")
    with patch.object(sheets, "_gc") as gc:
        sheets.export_to_sheets([VACANCY])
        sheets.export_rejected_to_sheets([VACANCY])
        assert sheets.pull_returns() == []
        gc.assert_not_called()


# --- отправка в чат ---

def _result(tier):
    r = MagicMock(); r.tier = tier; r.score = 100 if tier != "C" else 0
    return r


def test_returned_vacancy_bypasses_tier_c_skip():
    vacancies = [{"id": 1, "status": "new"}, {"id": 2, "status": "returned"}, {"id": 3, "status": "new"}]
    scores = {1: _result("C"), 2: _result("C"), 3: _result("A")}
    with patch.object(moderator.config, "TELEGRAM_BOT_TOKEN", "x"), \
         patch.object(moderator.config, "TELEGRAM_MODERATION_CHAT_RU", "y"), \
         patch.object(moderator.database, "get_new_vacancies", return_value=vacancies), \
         patch.object(moderator.database, "mark_skipped") as skip, \
         patch.object(moderator, "_get_or_score", side_effect=lambda v: scores[v["id"]]), \
         patch.object(moderator, "send_to_moderation", return_value=True) as send, \
         patch.object(moderator, "export_to_sheets") as exp_sent, \
         patch.object(moderator, "export_rejected_to_sheets") as exp_rej, \
         patch.object(moderator.time, "sleep"):
        assert moderator.send_new_vacancies_to_moderation() == 2
    assert sorted(c.args[0]["id"] for c in send.call_args_list) == [2, 3]
    assert [c.args[0] for c in skip.call_args_list] == [1]
    assert sorted(v["id"] for v in exp_sent.call_args.args[0]) == [2, 3]
    assert [v["id"] for v in exp_rej.call_args.args[0]] == [1]


# --- статусы в БД ---

@pytest.fixture
def db_vacancy():
    url = os.environ.get("DATABASE_URL", "")
    if "localhost" not in url:
        pytest.skip("нужна локальная Postgres (DATABASE_URL на localhost)")
    import database
    import psycopg2
    database.init_db()
    conn = psycopg2.connect(url); cur = conn.cursor()
    cur.execute("""INSERT INTO vacancies (source, title, hash, status, channel, parsed_at)
                   VALUES ('test', 'Test PM', %s, 'skipped', 'ru', %s) RETURNING id""",
                (f"test-decisions-{datetime.now().timestamp()}", datetime.now(timezone.utc).isoformat()))
    vid = cur.fetchone()[0]; conn.commit()
    yield database, vid, cur, conn
    cur.execute("DELETE FROM vacancies WHERE id = %s", (vid,)); conn.commit(); conn.close()


def test_decision_and_return_statuses(db_vacancy):
    database, vid, cur, conn = db_vacancy
    assert database.mark_returned([vid]) == 1
    assert any(v["id"] == vid for v in database.get_new_vacancies())

    database.mark_decision(vid, "declined", "гео")
    cur.execute("SELECT status, decision, decision_reason, decided_at FROM vacancies WHERE id=%s", (vid,))
    status, decision, reason, decided_at = cur.fetchone()
    assert (status, decision, reason) == ("declined", "declined", "гео") and decided_at is not None
    assert database.mark_returned([vid]) == 0  # твоё решение возврат не перетирает


def test_snoozed_comes_back_when_due(db_vacancy):
    database, vid, cur, conn = db_vacancy
    database.mark_snoozed(vid, datetime.now(timezone.utc) + timedelta(hours=3))
    assert all(v["id"] != vid for v in database.get_due_snoozed())
    database.mark_snoozed(vid, datetime.now(timezone.utc) - timedelta(minutes=1))
    assert any(v["id"] == vid for v in database.get_due_snoozed())


def test_cards_per_cycle_are_capped():
    vacancies = [{"id": i, "status": "new"} for i in range(1, 6)]
    with patch.object(moderator.config, "TELEGRAM_BOT_TOKEN", "x"), \
         patch.object(moderator.config, "TELEGRAM_MODERATION_CHAT_RU", "y"), \
         patch.object(moderator.config, "MODERATION_MAX_PER_CYCLE", 2), \
         patch.object(moderator.database, "get_new_vacancies", return_value=vacancies), \
         patch.object(moderator.database, "mark_skipped"), \
         patch.object(moderator, "_get_or_score", return_value=_result("A")), \
         patch.object(moderator, "send_to_moderation", return_value=True) as send, \
         patch.object(moderator, "export_to_sheets"), \
         patch.object(moderator, "export_rejected_to_sheets"), \
         patch.object(moderator.time, "sleep"):
        assert moderator.send_new_vacancies_to_moderation() == 2
    assert send.call_count == 2


@pytest.mark.parametrize("stored_version,rescored", [("v3", True), (moderator.PROMPT_VERSION, False)])
def test_score_of_other_version_is_recomputed(stored_version, rescored):
    row = {"prompt_version": stored_version, "tier": "A", "action": "curated", "score": 100,
           "visa_sponsorship": "unclear", "relocation_support": "unclear"}
    fresh = _result("B")
    with patch.object(moderator.database, "get_latest_vacancy_score", return_value=row), \
         patch.object(moderator.database, "save_vacancy_score"), \
         patch.object(moderator, "score_vacancy", return_value=fresh) as score:
        moderator._get_or_score({"id": 5})
    assert score.called is rescored


def test_only_fresh_vacancies_reach_chat():
    now = datetime.now(timezone.utc)
    vacancies = [
        {"id": 1, "status": "new", "published_at": now - timedelta(days=10)},
        {"id": 2, "status": "new", "published_at": now - timedelta(days=1)},
        {"id": 3, "status": "new", "published_at": None, "parsed_at": (now - timedelta(days=9)).isoformat()},
        {"id": 4, "status": "returned", "published_at": now - timedelta(days=30)},
        {"id": 5, "status": "new", "published_at": "2026-09-14T10:00:00+0300" if False else (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S+0300")},
    ]
    with patch.object(moderator.config, "TELEGRAM_BOT_TOKEN", "x"), \
         patch.object(moderator.config, "TELEGRAM_MODERATION_CHAT_RU", "y"), \
         patch.object(moderator.config, "MAX_VACANCY_AGE_DAYS", 7), \
         patch.object(moderator.database, "get_new_vacancies", return_value=vacancies), \
         patch.object(moderator.database, "mark_stale") as stale, \
         patch.object(moderator.database, "mark_skipped"), \
         patch.object(moderator, "_get_or_score", return_value=_result("A")), \
         patch.object(moderator, "send_to_moderation", return_value=True) as send, \
         patch.object(moderator, "export_to_sheets"), \
         patch.object(moderator, "export_rejected_to_sheets") as exp_rej, \
         patch.object(moderator.time, "sleep"):
        moderator.send_new_vacancies_to_moderation()
    assert sorted(c.args[0]["id"] for c in send.call_args_list) == [2, 4, 5]
    assert sorted(c.args[0] for c in stale.call_args_list) == [1, 3]
    stale_export = next(c.args[0] for c in exp_rej.call_args_list if c.args[0] and "Старше" in c.args[0][0]["_reject_reason"])
    assert sorted(v["id"] for v in stale_export) == [1, 3]


def test_dedup_ignores_punctuation_and_case(db_vacancy):
    database, vid, cur, conn = db_vacancy
    cur.execute("UPDATE vacancies SET title = %s, company = %s WHERE id = %s",
                ("Бизнес-аналитик (Юг России)", "ООО «Ромашка»", vid))
    conn.commit()
    assert database.vacancy_exists_by_title_company("бизнес аналитик — Юг России.", "ООО Ромашка")
    assert not database.vacancy_exists_by_title_company("Бизнес-аналитик (Москва)", "ООО «Ромашка»")


def test_card_footer_shows_score_without_old_scale():
    from scoring.models import ScoringResult
    result = ScoringResult(
        vacancy_id=1, tier="S", action="curated_plus", score=161, score_breakdown={}, ats_score=92,
        visa_sponsorship="unclear", relocation_support="unclear", remote_policy="global",
        salary_min=None, salary_max=None, salary_currency=None, experience_level="senior",
        verbatim_evidence={}, pre_filter_blocked=False, regex_completeness_score=1.0,
        enrichment_used=False, completeness_score=1.0, needs_enrichment=False, post_enrichment=None,
        reason="ATS 92% · совпало: jira",
    )
    with patch.object(moderator.database, "is_visa_sponsor", return_value=None):
        footer = moderator._scoring_footer(result, {"channel": "ru", "source": "hh.ru"})
    assert "/10" not in footer
    assert "скор 161" in footer and "ATS 92%" in footer


def test_money_report_is_silent_without_services():
    from bot import alerts
    with patch.object(alerts, "_railway_status", return_value=None), \
         patch.object(alerts, "send_alert") as send:
        alerts.money_report()
    send.assert_not_called()


def test_zero_limit_sends_nothing():
    with patch.object(moderator.database, "get_new_vacancies") as get:
        assert moderator.send_new_vacancies_to_moderation(limit=0) == 0
        get.assert_not_called()


def test_run_cycle_calls_hook_after_each_parser():
    import scheduler
    parsers = [MagicMock(source_name="a", run=MagicMock(return_value=[])),
               MagicMock(source_name="b", run=MagicMock(return_value=[]))]
    calls = []
    hook = MagicMock(side_effect=lambda: calls.append(len(calls)))
    with patch.object(scheduler.database, "record_parser_runs"), \
         patch.object(scheduler, "export_rejected_to_sheets"):
        scheduler.run_cycle(parsers=parsers, after_parser=hook)
    assert hook.call_count == 2


def test_full_cycle_sends_during_cycle_and_respects_budget(monkeypatch):
    import bot_app
    sent_limits = []
    def fake_send(limit=None):
        sent_limits.append(limit)
        return 7
    def fake_run_cycle(parsers=None, after_parser=None):
        after_parser(); after_parser()
        return {"parsed": 5, "saved": 3}
    monkeypatch.setattr(bot_app.config, "MODERATION_MAX_PER_CYCLE", 20)
    monkeypatch.setattr(bot_app, "send_new_vacancies_to_moderation", fake_send)
    monkeypatch.setattr(bot_app, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(bot_app, "_pull_returns", lambda: 0)
    monkeypatch.setattr(bot_app, "send_alert", lambda *a, **k: None)
    bot_app.full_cycle()
    assert sent_limits == [20, 13, 6]  # до цикла и после каждого из двух источников


def test_full_cycle_skips_when_previous_still_running(monkeypatch):
    import bot_app
    run = MagicMock()
    monkeypatch.setattr(bot_app, "run_cycle", run)
    assert bot_app._cycle_lock.acquire(blocking=False)
    try:
        bot_app.full_cycle()
    finally:
        bot_app._cycle_lock.release()
    run.assert_not_called()


def test_tg_call_retries_only_when_not_connected():
    import requests
    from bot import tg_api
    ok = MagicMock(); ok.json.return_value = {"ok": True, "result": {}}
    with patch.object(tg_api.requests, "post", side_effect=[requests.ConnectionError("down"), ok]) as post, \
         patch.object(tg_api.time, "sleep"):
        assert tg_api.call("sendMessage", chat_id=1, text="x")["ok"]
    assert post.call_count == 2
    with patch.object(tg_api.requests, "post", side_effect=requests.exceptions.ReadTimeout("slow")) as post, \
         patch.object(tg_api.time, "sleep"):
        with pytest.raises(RuntimeError):
            tg_api.call("sendMessage", chat_id=1, text="x")
    assert post.call_count == 1


def _scored(vid, source, tier, score, status="new"):
    r = MagicMock(); r.tier = tier; r.score = score
    return ({"id": vid, "source": source, "status": status}, r)


def test_fair_order_mixes_sources_within_tier():
    items = [_scored(i, "hh.ru", "S", 200 - i) for i in range(1, 6)]
    items += [_scored(10, "habr_career", "S", 140), _scored(11, "rabota.ru", "A", 190),
              _scored(12, "geekjob", "C", 50, status="returned")]
    order = [v["id"] for v, _ in moderator._fair_order(items)]
    assert order[0] == 12                  # возвращённая — первой
    assert order[1:4] == [1, 10, 2]        # S: по кругу hh / habr / hh
    assert order.index(11) > order.index(5)  # A после всех S, даже со скором выше


def _scored_at(vid, source, tier, score, hours_ago):
    v, r = _scored(vid, source, tier, score)
    v["published_at"] = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return v, r


def test_fresh_vacancy_goes_first_within_tier():
    items = [_scored_at(1, "hh.ru", "S", 150, hours_ago=100),   # 4 дня: 150
             _scored_at(2, "hh.ru", "S", 130, hours_ago=2),     # 2 часа: 130 + 40
             _scored_at(3, "hh.ru", "S", 200, hours_ago=100),   # сильно лучше, но старая: 200
             _scored_at(4, "hh.ru", "A", 120, hours_ago=1)]     # свежая, но тир ниже
    order = [v["id"] for v, _ in moderator._fair_order(items)]
    assert order == [3, 2, 1, 4]


def test_freshness_bonus_steps():
    now = datetime.now(timezone.utc)
    bonus = lambda h: moderator._freshness_bonus({"published_at": now - timedelta(hours=h)})
    assert (bonus(1), bonus(12), bonus(48), bonus(100)) == (40, 25, 10, 0)
    assert moderator._freshness_bonus({"published_at": None, "parsed_at": None}) == 0

