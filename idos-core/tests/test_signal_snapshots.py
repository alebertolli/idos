from pathlib import Path

import pytest

from idos.strategy.signals import SignalEvidenceError, current_selection


POLICY = {"minimum_signal": 0.6, "maximum_signal": 2.7, "select_top": 2}
SIGNAL = {"ticker": "XLF", "momentum": 0.9, "as_of_date": "2026-10-01"}


def test_newer_bounded_run_for_another_asset_does_not_supersede_selection(tmp_path, systematic_snapshot):
    path = systematic_snapshot(SIGNAL, POLICY)
    systematic_snapshot({**SIGNAL, "ticker": "QQQ"}, POLICY, generated_at="2026-10-18T13:00:00-03:00")
    evidence = current_selection(tmp_path, "MOMENTUM_ETF", "XLF", POLICY)
    assert evidence["signal"] == SIGNAL
    assert evidence["source"] == path.relative_to(tmp_path).as_posix()


@pytest.mark.parametrize("scope", ["bounded", "full"])
def test_negative_newer_run_never_falls_back_to_previous_selection(tmp_path, systematic_snapshot, scope):
    systematic_snapshot(SIGNAL, POLICY)
    systematic_snapshot(SIGNAL, POLICY, generated_at="2026-10-18T13:00:00-03:00",
                        selected=[], action="CASH_FALLBACK", run_scope=scope,
                        requested_tickers=[] if scope == "full" else ["XLF"])
    with pytest.raises(SignalEvidenceError, match="not_selected"):
        current_selection(tmp_path, "MOMENTUM_ETF", "XLF", POLICY)


@pytest.mark.parametrize("patch,reason", [
    ({"coverage_complete": False}, "incomplete"),
    ({"market_gate": []}, "incomplete"),
    ({"signal_policy": {}}, "policy_changed"),
    ({"ranking": []}, "invalid_signal_evidence"),
    ({"strategy_id": "COMPOUNDER"}, "invalid_signal_snapshot"),
    ({"generated_at": "2026-10-18T12:00:00"}, "invalid_signal_snapshot"),
])
def test_incomplete_or_mismatched_snapshot_cannot_authorize_review(tmp_path, systematic_snapshot, patch, reason):
    systematic_snapshot(SIGNAL, POLICY, **patch)
    with pytest.raises(SignalEvidenceError, match=reason):
        current_selection(tmp_path, "MOMENTUM_ETF", "XLF", POLICY)


def test_legacy_report_does_not_count_as_current_evidence(tmp_path, systematic_snapshot):
    systematic_snapshot(SIGNAL, POLICY, generated_at=None)
    with pytest.raises(SignalEvidenceError, match="unavailable"):
        current_selection(tmp_path, "MOMENTUM_ETF", "XLF", POLICY)


def test_corrupt_report_fails_closed(tmp_path, systematic_snapshot):
    path = systematic_snapshot(SIGNAL, POLICY)
    path.write_text("[unclosed", encoding="utf-8")
    with pytest.raises(SignalEvidenceError, match="invalid_signal_snapshot"):
        current_selection(tmp_path, "MOMENTUM_ETF", "XLF", POLICY)
