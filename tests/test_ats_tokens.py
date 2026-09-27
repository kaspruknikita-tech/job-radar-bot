"""
Тесты авто-харвеста ATS-токенов: merge seed+БД, дедуп harvest, дедуп ночного probe.
Без сети и без реальной БД — всё замокано.
Запуск: poetry run pytest tests/test_ats_tokens.py -v
"""
from unittest.mock import patch

from parsers._ats_tokens import merge_companies


# ---------------------------------------------------------------------------
# merge_companies — seed + БД, дедуп регистронезависимо, порядок seed
# ---------------------------------------------------------------------------

def test_merge_appends_db_tokens():
    seed = ["OpenAI", "Linear"]
    with patch("parsers._ats_tokens.database.load_ats_tokens", return_value=["foo", "bar"]):
        assert merge_companies(seed, "ashby") == ["OpenAI", "Linear", "foo", "bar"]


def test_merge_dedups_case_insensitive():
    seed = ["OpenAI", "Linear"]
    # "openai" из БД — дубль seed-токена "OpenAI", не должен попасть второй раз
    with patch("parsers._ats_tokens.database.load_ats_tokens", return_value=["openai", "foo"]):
        assert merge_companies(seed, "ashby") == ["OpenAI", "Linear", "foo"]


def test_merge_keeps_seed_order_first():
    seed = ["b", "a"]
    with patch("parsers._ats_tokens.database.load_ats_tokens", return_value=["c"]):
        assert merge_companies(seed, "lever") == ["b", "a", "c"]


def test_merge_falls_back_to_seed_on_db_error():
    seed = ["OpenAI"]
    with patch("parsers._ats_tokens.database.load_ats_tokens", side_effect=RuntimeError("db down")):
        assert merge_companies(seed, "ashby") == ["OpenAI"]


# ---------------------------------------------------------------------------
# harvest — извлечение токенов из URL и дедуп против all_companies()
# ---------------------------------------------------------------------------

def test_extract_tokens_from_urls():
    from tools.ats_harvest import _extract_tokens
    urls = [
        "https://jobs.ashbyhq.com/acme/123",
        "https://jobs.lever.co/widgetco/456",
        "https://example.com/not-ats",
    ]
    found = _extract_tokens(urls)
    assert "acme" in found["ashby"]
    assert "widgetco" in found["lever"]


def test_harvest_skips_known_saves_new():
    from tools import ats_harvest

    fake_mod = type("M", (), {"all_companies": staticmethod(lambda: ["acme"])})

    # Порядок важен: патч importlib.import_module меняет ГЛОБАЛЬНЫЙ importlib и
    # ломает резолвер mock для последующих патчей — ставим его последним.
    with patch("database.save_ats_token", return_value=True) as save, \
         patch.dict(ats_harvest._VALIDATORS, {"ashby": lambda t: True}, clear=False), \
         patch("tools.ats_harvest.importlib.import_module", return_value=fake_mod):
        added = ats_harvest.harvest_ats_tokens(
            ["https://jobs.ashbyhq.com/acme/1", "https://jobs.ashbyhq.com/newco/2"]
        )

    # acme уже известен (all_companies) → не сохраняем; newco новый и валидный → сохраняем
    save.assert_called_once_with("ashby", "newco", source="harvest")
    assert added["ashby"] == ["newco"]


# ---------------------------------------------------------------------------
# night probe — пропуск уже покрытых и уже опробованных
# ---------------------------------------------------------------------------

def test_night_probe_dedup():
    from tools import ats_night_probe as np

    names = ["Acme", "Known"]
    # Known уже покрыт в ashby (есть в all_companies)
    loaders = {
        "ashby": lambda: ["known"],
        "greenhouse": lambda: [],
        "lever": lambda: [],
    }
    # (acme, lever) уже пробовали раньше → lever для Acme пропускаем
    probed = {("acme", "lever")}

    def fake_check_ashby(t):
        return t == "acme"  # Acme находится на ashby

    # _CHECKERS забиндил функции в момент импорта — патчим сам словарь
    checkers = {"ashby": fake_check_ashby, "greenhouse": lambda t: False, "lever": lambda t: False}

    with patch.dict(np._COMPANY_LOADERS, loaders, clear=True), \
         patch.dict(np._CHECKERS, checkers, clear=True), \
         patch("database.get_recent_companies", return_value=names), \
         patch("database.get_probed_pairs", return_value=probed), \
         patch("database.save_ats_token", return_value=True) as save, \
         patch("database.record_probed_name") as rec:
        found = np.run_night_probe()

    assert found["ashby"] == ["acme"]
    save.assert_called_once_with("ashby", "acme", source="night_probe")

    recorded = {(c.args[0], c.args[1], c.args[2]) for c in rec.call_args_list}
    # Acme/ashby — попадание
    assert ("Acme", "ashby", "hit:acme") in recorded
    # Known покрыт в ashby → помечен covered
    assert ("Known", "ashby", "covered") in recorded
    # (acme, lever) уже пробован → НЕ записываем повторно
    assert not any(name == "Acme" and ats == "lever" for name, ats, _ in recorded)
