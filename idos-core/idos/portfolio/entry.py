from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase, WyckoffResult
from idos.timezone import AR_TZ

WYCOFF_CONFIDENCE_MULTIPLIER: dict[str, float] = {
    "alta": 1.5,
    "media": 1.0,
    "baja": 0.5,
}

WYCOFF_SCORE_THRESHOLD: int = 65


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


class EntryEngine:
    def __init__(self,
                 wyckoff_analyzer: WyckoffAnalyzer | None = None,
                 min_margin_of_safety: float = 30.0,
                 min_wyckoff_score: int = WYCOFF_SCORE_THRESHOLD,
                 llm_client: Optional[LLMClient] = None,
                 prompt_registry: Optional[PromptRegistry] = None):
        if wyckoff_analyzer:
            self.wyckoff = wyckoff_analyzer
        else:
            self.wyckoff = WyckoffAnalyzer(
                llm_client=llm_client,
                prompt_registry=prompt_registry,
            )
        self.min_margin_of_safety = min_margin_of_safety
        self.min_wyckoff_score = min_wyckoff_score

    def evaluate(self, ticker: str, context: dict[str, Any]) -> EntrySignal:
        price_data = context.get("price_data", [])
        intrinsic = context.get("intrinsic_value", 0)
        current_price = context.get("current_price", 0)
        thesis_active = context.get("thesis_active", True)
        portfolio = context.get("portfolio", {})

        margin = ((intrinsic - current_price) / current_price * 100) if current_price and intrinsic else 0
        price_in_zone = margin >= self.min_margin_of_safety

        result: WyckoffResult = self.wyckoff.analyze(price_data)
        wyckoff_ok = self.wyckoff.is_entry_confirmed(result.phase)
        has_llm = result.raw_llm_response is not None and result.confidence_label != ""
        wyckoff_score_ok = result.score >= self.min_wyckoff_score if has_llm else True
        wyckoff_confirmed = wyckoff_ok and wyckoff_score_ok

        proposed_weight = context.get("proposed_weight", 3.0)
        multiplier = WYCOFF_CONFIDENCE_MULTIPLIER.get(result.confidence_label, 1.0)
        adjusted_weight = round(proposed_weight * multiplier, 2)

        pf_ok = True
        total_weight = portfolio.get("total_weight", 0)
        if total_weight + adjusted_weight > 20:
            pf_ok = False

        all_ok = all([price_in_zone, wyckoff_confirmed, thesis_active, pf_ok])

        return EntrySignal(
            ticker=ticker.upper(),
            price_in_zone=price_in_zone,
            wyckoff_confirmed=wyckoff_confirmed,
            thesis_active=thesis_active,
            portfolio_fit=pf_ok,
            all_conditions_met=all_ok,
            current_price=current_price,
            target_price=intrinsic,
            margin_of_safety_pct=round(margin, 1),
            wyckoff_phase=result.phase.value,
            reason="Entry conditions met" if all_ok else f"Blocked: price_ok={price_in_zone}, wyckoff={wyckoff_confirmed}(score={result.score}), thesis={thesis_active}, pf={pf_ok}{', LLM score bypassed' if not has_llm else ''}",
            wyckoff_raw=result.raw_llm_response,
            wyckoff_indicators=result.indicators if result.indicators else None,
            wyckoff_score=result.score,
            wyckoff_confidence=result.confidence_label,
            wyckoff_entry_point=result.entry_point,
            wyckoff_stop_loss=result.wyckoff_stop_loss,
            wyckoff_price_target=result.wyckoff_price_target,
            adjusted_weight=adjusted_weight,
        )
