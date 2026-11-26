from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.continue_ddd_research import dispatch_if_due
from idos.research.hourly_ramp import defer_provider_retry, initial_state


def test_continuation_dispatches_one_bounded_resume_for_due_work():
    calls = []
    dispatched = dispatch_if_due(
        initial_state(),
        [{"ticker": "AAPL", "opp_id": "OPP-AAPL", "next_attempt_date": "2026-11-19"}],
        repository="alebertolli/idos",
        now=datetime(2026, 11, 19, 12, tzinfo=timezone.utc),
        run=lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert dispatched
    command, kwargs = calls[0]
    assert command[:5] == ["gh", "workflow", "run", "ddd-pipeline.yml", "--repo"]
    assert "continue_hourly_ramp=true" in command
    assert "allow_production_e2e=true" in command
    assert kwargs == {"check": True}


def test_continuation_does_not_dispatch_during_provider_cooldown():
    calls = []
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    state = defer_provider_retry(initial_state(), now=now)

    dispatched = dispatch_if_due(
        state,
        [{"ticker": "AAPL", "opp_id": "OPP-AAPL", "next_attempt_date": "2026-11-19"}],
        repository="alebertolli/idos",
        now=now,
        run=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert not dispatched
    assert calls == []



def test_continuation_does_not_dispatch_when_all_due_work_is_quarantined():
    calls = []
    now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
    pending = [{"ticker": "XLF", "opp_id": "OPP-XLF", "next_attempt_date": "2026-11-23"}]
    quarantined = [{"ticker": "xlf", "opp_id": "OPP-XLF"}]

    dispatched = dispatch_if_due(
        initial_state(),
        pending,
        repository="alebertolli/idos",
        now=now,
        quarantined=quarantined,
        run=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert not dispatched
    assert calls == []


def test_continuation_keeps_due_candidates_not_in_quarantine():
    calls = []
    now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
    pending = [
        {"ticker": "XLF", "opp_id": "OPP-XLF", "next_attempt_date": "2026-11-23"},
        {"ticker": "ASML", "opp_id": "OPP-ASML", "next_attempt_date": "2026-11-23"},
    ]

    dispatched = dispatch_if_due(
        initial_state(),
        pending,
        repository="alebertolli/idos",
        now=now,
        quarantined=[{"ticker": "XLF", "opp_id": "OPP-XLF"}],
        run=lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert dispatched
    assert len(calls) == 1
