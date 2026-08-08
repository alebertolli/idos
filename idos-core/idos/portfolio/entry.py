from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from idos.config import Settings, load_settings
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase, WyckoffResult
from idos.timezone import AR_TZ

WYCOFF_CONFIDENCE_MULTIPLIER: dict[str, float] = {
    "alta": 1.5,
    "media": 1.0,
    "baja": 0.5,
}

WYCOFF_SCORE_THRESHOLD: int = 45


@dataclass
class EntrySignal:
    ticker: str
    price_in_zone: bool = False
    wyckoff_confirmed: bool = False
    thesis_active: bool = False
    portfolio_fit: bool = False
    all_conditions_met: bool = False
    current_price: float = 0.0
    target_price: float = 0.0
    margin_of_safety_pct: float = 0.0
    wyckoff_phase: str = ""
    reason: str = ""
    wyckoff_raw: dict | None = None
    wyckoff_indicators: dict | None = None
    wyckoff_score: int = 0
    wyckoff_confidence: str = ""
    wyckoff_entry_point: str = ""
    wyckoff_stop_loss: float | None = None
    wyckoff_price_target: float | None = None
    adjusted_weight: float = 0.0
    llm_error: str = ""
    target_missing: bool = False


class EntryEngine:
    def __init__(self,
                 wyckoff_analyzer: WyckoffAnalyzer | None = None,
                 min_margin_of_safety: float = 30.0,
                 min_wyckoff_score: int = WYCOFF_SCORE_THRESHOLD,
                 settings: Settings | None = None,
                 config_dir: str | Path | None = None):
        if settings is None and config_dir is not None:
            settings = load_settings(config_dir)
        self.settings = settings
        self.wyckoff = wyckoff_analyzer or WyckoffAnalyzer()
        self.min_margin_of_safety = min_margin_of_safety
        self.min_wyckoff_score = min_wyckoff_score

    @property
    def max_total_weight_pct(self) -> float:
        if self.settings is not None:
            return float(self.settings.portfolio.get("max_total_weight_pct", 20.0))
        return 20.0

    def evaluate(self, ticker: str, context: dict[str, Any]) -> EntrySignal:
        price_data = context.get("price_data", [])
        intrinsic = context.get("intrinsic_value", 0)
        current_price = context.get("current_price", 0)
        thesis_active = context.get("thesis_active", True)
        portfolio = context.get("portfolio", {})
        benchmark_data = context.get("benchmark_data")
        target_price = context.get("target_price") or intrinsic
        buy_zone_top = context.get("buy_zone_top", 0)

        target_missing = not target_price or target_price <= 0

        margin = ((intrinsic - current_price) / current_price * 100) if current_price and intrinsic else 0

        if buy_zone_top and buy_zone_top > 0 and current_price:
            price_in_zone = current_price <= buy_zone_top
        else:
            price_in_zone = margin >= self.min_margin_of_safety

        result: WyckoffResult = self.wyckoff.analyze(price_data, benchmark_data=benchmark_data)
        wyckoff_ok = self.wyckoff.is_entry_confirmed(result.phase)
        wyckoff_score_ok = result.score >= self.min_wyckoff_score
        wyckoff_confirmed = wyckoff_ok and wyckoff_score_ok

        proposed_weight = context.get("proposed_weight", 3.0)
        multiplier = WYCOFF_CONFIDENCE_MULTIPLIER.get(result.confidence_label, 1.0)
        adjusted_weight = round(proposed_weight * multiplier, 2)

        pf_ok = True
        total_weight = portfolio.get("total_weight", 0)
        if total_weight + adjusted_weight > self.max_total_weight_pct:
            pf_ok = False

        all_ok = all([price_in_zone, wyckoff_confirmed, thesis_active, pf_ok, not target_missing])

        return EntrySignal(
            ticker=ticker.upper(),
            price_in_zone=price_in_zone,
            wyckoff_confirmed=wyckoff_confirmed,
            thesis_active=thesis_active,
            portfolio_fit=pf_ok,
            all_conditions_met=all_ok,
            current_price=current_price,
            target_price=float(target_price or 0),
            margin_of_safety_pct=round(margin, 1),
            wyckoff_phase=result.phase.value,
            reason="Entry conditions met" if all_ok else
                f"Blocked: price_ok={price_in_zone}, wyckoff={wyckoff_confirmed}(score={result.score}), "
                f"thesis={thesis_active}, pf={pf_ok}, target_missing={target_missing}",
            wyckoff_raw=result.raw_llm_response,
            wyckoff_indicators=result.indicators if result.indicators else None,
            wyckoff_score=result.score,
            wyckoff_confidence=result.confidence_label,
            wyckoff_entry_point=result.entry_point,
            wyckoff_stop_loss=result.wyckoff_stop_loss,
            wyckoff_price_target=result.wyckoff_price_target,
            adjusted_weight=adjusted_weight,
            llm_error=result.llm_error,
            target_missing=target_missing,
        )
