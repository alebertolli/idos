import json

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
