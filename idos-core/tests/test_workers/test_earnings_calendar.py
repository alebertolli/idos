import json

import yaml

from idos.workers.data import earnings_calendar


def test_earnings_loader_ignores_non_object_cache_files(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "series.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    (cache / "nested-list.json").write_text(
        json.dumps({"merged_data": [1, 2, 3]}), encoding="utf-8"
    )
    (cache / "AAPL.json").write_text(
        json.dumps({"merged_data": {"next_earnings_date": 1_800_000_000}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(earnings_calendar, "CACHE_DIR", cache)

    result = earnings_calendar._load_cache_tickers()

    assert set(result) == {"AAPL"}


def test_earnings_loader_recovers_from_non_mapping_config(tmp_path, monkeypatch):
    config_file = tmp_path / "earnings.yml"
    config_file.write_text("tickers:\n  - AAPL\n", encoding="utf-8")
    monkeypatch.setattr(earnings_calendar, "EARNINGS_CONFIG_PATH", config_file)

    assert earnings_calendar._load_existing_config() == {"tickers": {}}


def test_new_earnings_date_resets_previous_trigger_and_preserves_metadata(
    tmp_path, monkeypatch
):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "AAPL.json").write_text(
        json.dumps({"merged_data": {"next_earnings_date": 1_800_000_000}}),
        encoding="utf-8",
    )
    config_file = tmp_path / "earnings.yml"
    config_file.write_text(
        "tickers:\n  AAPL:\n    earnings_date: '2026-07-30'\n"
        "    triggered_at: '2026-08-01'\n    alias_of: null\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(earnings_calendar, "CACHE_DIR", cache)
    monkeypatch.setattr(earnings_calendar, "EARNINGS_CONFIG_PATH", config_file)
    monkeypatch.setattr(
        earnings_calendar, "_timestamp_to_date", lambda _: "2026-11-05"
    )

    result = earnings_calendar.populate_earnings()
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    assert result["updated"] == ["AAPL"]
    assert saved["tickers"]["AAPL"] == {
        "earnings_date": "2026-11-05",
        "triggered_at": None,
        "alias_of": None,
    }


def test_unchanged_earnings_date_keeps_trigger_and_is_idempotent(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "AAPL.json").write_text(
        json.dumps({"merged_data": {"next_earnings_date": 1_800_000_000}}),
        encoding="utf-8",
    )
    config_file = tmp_path / "earnings.yml"
    config_file.write_text(
        "tickers:\n  AAPL:\n    earnings_date: '2026-11-05'\n"
        "    triggered_at: '2026-11-07'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(earnings_calendar, "CACHE_DIR", cache)
    monkeypatch.setattr(earnings_calendar, "EARNINGS_CONFIG_PATH", config_file)
    monkeypatch.setattr(
        earnings_calendar, "_timestamp_to_date", lambda _: "2026-11-05"
    )

    result = earnings_calendar.populate_earnings()
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    assert result["updated"] == []
    assert result["skipped"] == ["AAPL"]
    assert saved["tickers"]["AAPL"]["triggered_at"] == "2026-11-07"
