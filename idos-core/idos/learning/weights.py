from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class WeightAdjustment:
    dimension: str
    old_weight: float
    new_weight: float
    change_pct: float
    hit_rate: float
    reason: str = ""
    adjusted_at: str = ""

    def __post_init__(self):
        if not self.adjusted_at:
            self.adjusted_at = datetime.now(AR_TZ).isoformat()

class WeightAdjuster:
    def __init__(self, base_weights: dict[str, float] | None = None,
                 min_weight: float = 0.05, max_weight: float = 0.50,
                 adjustment_rate: float = 0.05):
        self._weights = base_weights or {}
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.adjustment_rate = adjustment_rate
        self._history: list[WeightAdjustment] = []

    def set_base_weights(self, weights: dict[str, float]):
        self._weights = dict(weights)

    def adjust(self, dimension: str, hit_rate: float, sample_size: int = 10) -> WeightAdjustment | None:
        if dimension not in self._weights or sample_size < 5:
            return None
        old = self._weights[dimension]
        adjustment = self.adjustment_rate * ((hit_rate - 50) / 50)
        new = old + adjustment
        new = max(self.min_weight, min(self.max_weight, new))
        if abs(new - old) < 0.005:
            return None
        self._weights[dimension] = round(new, 3)
        adj = WeightAdjustment(
            dimension=dimension, old_weight=round(old, 3),
            new_weight=round(new, 3),
            change_pct=round((new - old) / old * 100, 1) if old else 0,
            hit_rate=hit_rate,
            reason=f"Hit rate {hit_rate}% {'improved' if new > old else 'reduced'} weight by {abs(new-old):.1%}",
        )
        self._history.append(adj)
        return adj

    def get_weight(self, dimension: str) -> float:
        return self._weights.get(dimension, 0.1)

    def get_all_weights(self) -> dict[str, float]:
        return dict(self._weights)

    def get_history(self) -> list[WeightAdjustment]:
        return list(self._history)

    def reset(self, dimension: str | None = None):
        if dimension:
            self._weights.pop(dimension, None)
        else:
            self._weights.clear()
        self._history.clear()
