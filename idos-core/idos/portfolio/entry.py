from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase
from idos.timezone import AR_TZ

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

class EntryEngine:
    def __init__(self,
                 wyckoff_analyzer: WyckoffAnalyzer | None = None,
                 min_margin_of_safety: float = 30.0,
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

    def evaluate(self, ticker: str, context: dict[str, Any]) -> EntrySignal:
        price_data = context.get("price_data", [])
        intrinsic = context.get("intrinsic_value", 0)
        current_price = context.get("current_price", 0)
        thesis_active = context.get("thesis_active", True)
        portfolio = context.get("portfolio", {})

        margin = ((intrinsic - current_price) / current_price * 100) if current_price and intrinsic else 0
        price_in_zone = margin >= self.min_margin_of_safety

        phase = self.wyckoff.analyze(price_data)
        wyckoff_ok = self.wyckoff.is_entry_confirmed(phase)

        pf_ok = True
        total_weight = portfolio.get("total_weight", 0)
        new_weight = context.get("proposed_weight", 3.0)
        if total_weight + new_weight > 20:
            pf_ok = False

        all_ok = all([price_in_zone, wyckoff_ok, thesis_active, pf_ok])

        return EntrySignal(
            ticker=ticker.upper(),
            price_in_zone=price_in_zone,
            wyckoff_confirmed=wyckoff_ok,
            thesis_active=thesis_active,
            portfolio_fit=pf_ok,
            all_conditions_met=all_ok,
            current_price=current_price,
            target_price=intrinsic,
            margin_of_safety_pct=round(margin, 1),
            wyckoff_phase=phase.value,
            reason="Entry conditions met" if all_ok else f"Blocked: price_ok={price_in_zone}, wyckoff={wyckoff_ok}, thesis={thesis_active}, pf={pf_ok}",
        )
