"""Deterministic thesis-review cadence helpers shared by workers and the site."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from idos.strategy.catalog import StrategyProfile
from idos.timezone import AR_TZ

DEFAULT_THESIS_REVIEW_INTERVAL_DAYS = 30


@dataclass(frozen=True)
class ThesisReviewSchedule:
    interval_days: int | None
    next_review_at: datetime | None
    due: bool
    reason: str


def interval_days_for(profile: StrategyProfile) -> int | None:
    """Return the configured interval, or None for strategies without a thesis."""
    if profile.is_systematic or profile.research_profile == "systematic":
        return None

    interval = profile.parameters.get(
        "thesis_review_interval_days", DEFAULT_THESIS_REVIEW_INTERVAL_DAYS,
    )
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        raise ValueError(
            f"{profile.strategy_id}.parameters.thesis_review_interval_days "
            "must be a positive integer"
        )
    return interval


def schedule_for_opportunity(
    opportunity: dict[str, Any],
    profile: StrategyProfile,
    now: datetime | None = None,
) -> ThesisReviewSchedule:
    """Compute a next-review date from the last thesis/research date.

    Missing or malformed dates fail open to an immediate review, while an
    invalid configured interval raises so configuration errors remain visible.
    """
    interval = interval_days_for(profile)
    if interval is None:
        return ThesisReviewSchedule(None, None, False, "systematic_strategy")

    anchor = _parse_date(
        opportunity.get("last_thesis_assessment_at")
        or opportunity.get("last_research_at")
        or opportunity.get("created_at")
        or opportunity.get("updated_at")
    )
    if anchor is None:
        stored_next = _parse_date(opportunity.get("next_thesis_review_at"))
        if stored_next is None:
            return ThesisReviewSchedule(interval, None, True, "missing_review_anchor")
        current = _as_aware(now or datetime.now(AR_TZ))
        due = stored_next <= current
        return ThesisReviewSchedule(
            interval, stored_next, due, "review_due" if due else "review_not_due",
        )

    next_review = anchor + timedelta(days=interval)
    current = _as_aware(now or datetime.now(AR_TZ))
    return ThesisReviewSchedule(
        interval_days=interval,
        next_review_at=next_review,
        due=next_review <= current,
        reason="review_due" if next_review <= current else "review_not_due",
    )


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    return _as_aware(parsed)


def _as_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=AR_TZ) if value.tzinfo is None else value
