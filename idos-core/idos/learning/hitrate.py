from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class HitRateStats:
    total: int = 0
    hits: int = 0
    misses: int = 0
    pending: int = 0
    hit_rate_pct: float = 0.0


class HitRateTracker:
    def __init__(self):
        self._records: dict[str, list[dict]] = {}

    def record_prediction(self, key: str, correct: bool | None = None):
        if key not in self._records:
            self._records[key] = []
        self._records[key].append({
            "correct": correct,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def record_hit(self, key: str):
        self.record_prediction(key, True)

    def record_miss(self, key: str):
        self.record_prediction(key, False)

    def record_pending(self, key: str):
        self.record_prediction(key, None)

    def stats(self, key: str) -> HitRateStats:
        records = self._records.get(key, [])
        hits = sum(1 for r in records if r["correct"] is True)
        misses = sum(1 for r in records if r["correct"] is False)
        pending = sum(1 for r in records if r["correct"] is None)
        total_closed = hits + misses
        return HitRateStats(
            total=len(records), hits=hits, misses=misses, pending=pending,
            hit_rate_pct=round(hits / total_closed * 100, 1) if total_closed else 0.0,
        )

    def all_keys(self) -> list[str]:
        return list(self._records.keys())

    def top_performers(self, min_samples: int = 5) -> list[tuple[str, HitRateStats]]:
        results = []
        for key in self._records:
            s = self.stats(key)
            if s.total >= min_samples and s.hit_rate_pct > 0:
                results.append((key, s))
        results.sort(key=lambda x: x[1].hit_rate_pct, reverse=True)
        return results

    def clear(self):
        self._records.clear()
