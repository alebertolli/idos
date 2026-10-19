from datetime import datetime, timedelta

import pytest

from idos.research.thesis_schedule import schedule_for_opportunity
from idos.strategy.catalog import StrategyProfile
from idos.timezone import AR_TZ


def _profile(parameters=None, **kwargs):
    return StrategyProfile(
        strategy_id=kwargs.get("strategy_id", "COMPOUNDER"),
        core="CORE_3_GROWTH",
        sleeve="HIGH_CONVICTION",
        thesis_type=kwargs.get("thesis_type", "STRATEGIC"),
        discovery_profile="compounder",
        research_profile=kwargs.get("research_profile", "strategic"),
        entry_policy="VALUATION_ZONE",
        enabled=True,
        parameters=parameters or {},
    )


def test_thesis_schedule_uses_profile_interval_and_marks_overdue():
    now = datetime(2026, 10, 19, 12, tzinfo=AR_TZ)
    opportunity = {"last_thesis_assessment_at": (now - timedelta(days=31)).isoformat()}

    schedule = schedule_for_opportunity(opportunity, _profile(), now)

    assert schedule.interval_days == 30
    assert schedule.due is True
    assert schedule.reason == "review_due"
    assert schedule.next_review_at == now - timedelta(days=1)


def test_profile_can_defer_review_until_its_configured_date():
    now = datetime(2026, 10, 19, 12, tzinfo=AR_TZ)
    opportunity = {"last_research_at": (now - timedelta(days=20)).isoformat()}

    schedule = schedule_for_opportunity(
        opportunity, _profile({"thesis_review_interval_days": 45}), now,
    )

    assert schedule.interval_days == 45
    assert schedule.due is False
    assert schedule.next_review_at == now + timedelta(days=25)


def test_systematic_strategy_has_no_fundamental_thesis_schedule():
    schedule = schedule_for_opportunity(
        {"created_at": "2020-01-01T00:00:00"},
        _profile(strategy_id="MOMENTUM_ETF", thesis_type="SYSTEMATIC", research_profile="systematic"),
    )

    assert schedule.interval_days is None
    assert schedule.next_review_at is None
    assert schedule.reason == "systematic_strategy"


def test_invalid_review_interval_fails_explicitly():
    with pytest.raises(ValueError, match="positive integer"):
        schedule_for_opportunity(
            {}, _profile({"thesis_review_interval_days": 0}),
        )


def test_missing_review_anchor_is_due_immediately():
    schedule = schedule_for_opportunity({}, _profile())

    assert schedule.due is True
    assert schedule.next_review_at is None
    assert schedule.reason == "missing_review_anchor"
