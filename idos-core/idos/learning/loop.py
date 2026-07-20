from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class LoopResult:
    weights_adjusted: int = 0
    patterns_identified: int = 0
    feedback_processed: int = 0
    hit_rates_updated: int = 0
    top_patterns: list[str] = field(default_factory=list)
    underperformers: list[str] = field(default_factory=list)
    completed_at: str = ""

    def __post_init__(self):
        if not self.completed_at:
            self.completed_at = datetime.now(AR_TZ).isoformat()

class ContinuousImprovementLoop:
    def __init__(self, feedback_collector, weight_adjuster,
                 pattern_learner, hit_rate_tracker):
        self.feedback = feedback_collector
        self.weights = weight_adjuster
        self.patterns = pattern_learner
        self.hitrates = hit_rate_tracker
        self._min_sample_for_adjustment = 5

    def run(self) -> LoopResult:
        result = LoopResult()

        feedback_records = self.feedback.all()
        result.feedback_processed = len(feedback_records)

        for dim in self.weights.get_all_weights():
            engine_records = [r for r in feedback_records if r.engine == dim]
            if len(engine_records) >= self._min_sample_for_adjustment:
                summary = self.feedback.summary(engine_records)
                adj = self.weights.adjust(dim, summary.hit_rate, len(engine_records))
                if adj:
                    result.weights_adjusted += 1

                key = f"engine:{dim}"
                for rec in engine_records:
                    if rec.outcome.value == "success":
                        self.hitrates.record_hit(key)
                    elif rec.outcome.value == "failure":
                        self.hitrates.record_miss(key)
                result.hit_rates_updated += 1

        top = self.patterns.get_high_performing(min_success_rate=70)
        result.top_patterns = [p.pattern_id for p in top]
        result.patterns_identified = len(top)

        under = self.patterns.get_underperforming(max_success_rate=40)
        result.underperformers = [p.pattern_id for p in under]

        return result
