from datetime import datetime, timezone
import json

import pytest
import yaml

from scripts.build_earnings_dispatch_payload import build_payload


def test_build_payload_preserves_source_for_each_triggered_ticker(tmp_path):
    trigger = tmp_path / "trigger.json"
    trigger.write_text(json.dumps({"triggered": ["ASML", "AAPL"]}), encoding="utf-8")
    config = tmp_path / "earnings.yml"
    config.write_text(yaml.safe_dump({"tickers": {
        "AAPL": {
            "earnings_date": "2026-10-14",
            "source_name": "Yahoo Finance earnings calendar via yfinance",
            "source_url": "https://finance.yahoo.com/calendar/earnings/?symbol=AAPL",
        },
        "ASML": {
            "earnings_date": "2026-10-15",
            "source_name": "Yahoo Finance earnings calendar via yfinance",
            "source_url": "https://finance.yahoo.com/calendar/earnings/?symbol=ASML",
        },
    }}), encoding="utf-8")

    payload = build_payload(
        trigger,
        config,
        observed_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
    )

    events = payload["client_payload"]["events"]
    assert payload["event_type"] == "quarterly-results"
    assert payload["client_payload"]["ticker"] == "AAPL,ASML"
    assert [item["ticker"] for item in events] == ["AAPL", "ASML"]
    assert events[1]["occurred_at"] == "2026-10-15"
    assert events[1]["observed_at"] == "2026-10-19T12:00:00+00:00"
    assert "verificar el resultado" in events[1]["summary"].lower()


def test_build_payload_rejects_trigger_without_source_metadata(tmp_path):
    trigger = tmp_path / "trigger.json"
    trigger.write_text(json.dumps({"triggered": ["AAPL"]}), encoding="utf-8")
    config = tmp_path / "earnings.yml"
    config.write_text("tickers:\n  AAPL:\n    earnings_date: '2026-10-14'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="procedencia"):
        build_payload(trigger, config)
