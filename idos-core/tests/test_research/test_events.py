from datetime import datetime, timezone
import json

import pytest

from idos.research.events import load_event_evidence, normalize_event_evidence


def event_record(ticker="ASML"):
    return {
        "ticker": ticker,
        "event_type": "quarterly_results",
        "occurred_at": "2026-10-14",
        "observed_at": "2026-10-19T11:00:00+00:00",
        "source_name": "ASML Investor Relations",
        "source_url": "https://www.asml.com/en/news/press-releases/2026/q3-results",
        "summary": "Quarterly results published; verify figures in the primary release.",
    }


def test_event_evidence_is_normalized_and_fingerprinted():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)

    normalized = normalize_event_evidence(
        "quarterly-results", "ASML", event_record(), now=now,
    )

    assert normalized["event_type"] == "quarterly_results"
    assert normalized["ticker"] == "ASML"
    assert normalized["event_id"]
    assert normalized["observed_at"] == "2026-10-19T11:00:00+00:00"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(source_url="http://example.com"), "HTTPS"),
        (lambda data: data.update(occurred_at="2026-10-20"), "futuro"),
        (lambda data: data.update(ticker="AAPL"), "ticker"),
        (lambda data: data.update(summary="x"), "summary"),
        (lambda data: data.update(observed_at="2026-10-19T11:00:00"), "zona horaria"),
    ],
)
def test_invalid_event_evidence_fails_closed(mutate, message):
    data = event_record()
    mutate(data)

    with pytest.raises(ValueError, match=message):
        normalize_event_evidence(
            "quarterly_results", "ASML", data,
            now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        )


def test_workflow_dispatch_reads_single_ticker_evidence(tmp_path, monkeypatch):
    payload_path = tmp_path / "event.json"
    payload_path.write_text(json.dumps({"inputs": {
        "event_date": "2026-10-14",
        "event_source_name": "ASML Investor Relations",
        "event_source_url": "https://www.asml.com/en/news/press-releases/2026/q3-results",
        "event_summary": "Quarterly results published; verify figures in the primary release.",
    }}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    evidence = load_event_evidence(
        "quarterly_results", "ASML", event_path=payload_path,
        now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
    )

    assert evidence["ticker"] == "ASML"
    assert evidence["event_type"] == "quarterly_results"


def test_repository_dispatch_selects_ticker_from_event_batch(tmp_path, monkeypatch):
    payload_path = tmp_path / "event.json"
    payload_path.write_text(json.dumps({"client_payload": {
        "events": [event_record("AAPL"), event_record("ASML")],
    }}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "repository_dispatch")

    evidence = load_event_evidence(
        "quarterly-results", "ASML", event_path=payload_path,
        now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
    )

    assert evidence["ticker"] == "ASML"
    assert evidence["source_name"] == "ASML Investor Relations"


def test_repository_dispatch_rejects_duplicate_or_missing_ticker(tmp_path, monkeypatch):
    payload_path = tmp_path / "event.json"
    payload_path.write_text(json.dumps({"client_payload": {
        "events": [event_record("AAPL"), event_record("AAPL")],
    }}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "repository_dispatch")

    with pytest.raises(ValueError, match="evidencia única"):
        load_event_evidence(
            "quarterly_results", "AAPL", event_path=payload_path,
            now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        )
