from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class Pattern:
    pattern_id: str
    description: str
    conditions: dict[str, Any]
    success_rate: float = 0.0
    occurrence_count: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    last_observed: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.last_observed:
            self.last_observed = self.created_at


class PatternLearner:
    def __init__(self, min_occurrences: int = 3):
        self.min_occurrences = min_occurrences
        self._patterns: dict[str, Pattern] = {}
        self._observations: list[dict[str, Any]] = []

    def observe(self, ticker: str, features: dict[str, Any], outcome: str):
        record = {"ticker": ticker, "features": dict(features), "outcome": outcome,
                  "timestamp": datetime.now(UTC).isoformat()}
        self._observations.append(record)
        self._match_patterns(record)

    def _match_patterns(self, record: dict[str, Any]):
        for pid, pattern in self._patterns.items():
            if self._matches(record["features"], pattern.conditions):
                pattern.occurrence_count += 1
                pattern.last_observed = datetime.now(UTC).isoformat()
                if record["outcome"] == "success":
                    old_total = pattern.occurrence_count - 1
                    pattern.success_rate = round(
                        ((pattern.success_rate * old_total) + 100) / pattern.occurrence_count, 1
                    )
                else:
                    old_total = pattern.occurrence_count - 1
                    pattern.success_rate = round(
                        (pattern.success_rate * old_total) / pattern.occurrence_count, 1
                    )

    def _matches(self, features: dict, conditions: dict) -> bool:
        for key, condition in conditions.items():
            value = features.get(key)
            if isinstance(condition, dict):
                if "min" in condition and (value is None or value < condition["min"]):
                    return False
                if "max" in condition and (value is None or value > condition["max"]):
                    return False
            elif isinstance(condition, list):
                if value not in condition:
                    return False
            elif condition is not None and value != condition:
                return False
        return True

    def register_pattern(self, pattern_id: str, description: str,
                          conditions: dict[str, Any], tags: list[str] | None = None):
        self._patterns[pattern_id] = Pattern(
            pattern_id=pattern_id, description=description,
            conditions=conditions, tags=tags or [],
        )

    def get_patterns_by_tag(self, tag: str) -> list[Pattern]:
        return [p for p in self._patterns.values() if tag in p.tags]

    def get_high_performing(self, min_success_rate: float = 70.0) -> list[Pattern]:
        return [
            p for p in self._patterns.values()
            if p.occurrence_count >= self.min_occurrences and p.success_rate >= min_success_rate
        ]

    def get_underperforming(self, max_success_rate: float = 40.0) -> list[Pattern]:
        return [
            p for p in self._patterns.values()
            if p.occurrence_count >= self.min_occurrences and p.success_rate <= max_success_rate
        ]

    def all_patterns(self) -> list[Pattern]:
        return list(self._patterns.values())

    def recent_observations(self, n: int = 20) -> list[dict[str, Any]]:
        return self._observations[-n:]
