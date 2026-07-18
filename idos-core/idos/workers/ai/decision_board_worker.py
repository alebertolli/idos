from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker


class DecisionBoardWorker(BaseWorker):
    """Evaluates DDD output against entry rules and proposes approval/rejection.

    Triggers: after ResearchWorker completes (UNDER_DEEP_DD).
    Transitions: UNDER_DEEP_DD -> APPROVED or WATCHLIST.
    """
    name = "decision_board_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.llm = LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()
        self.state_machine = OpportunityStateMachine()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)

        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            msg = f"Opportunity {opp_id} not found"
            raise ValueError(msg)

        current_status = OpportunityStatus(opp["status"])
        if not self.state_machine.can_transition(current_status, OpportunityStatus.APPROVED):
            can_watchlist = self.state_machine.can_transition(current_status, OpportunityStatus.WATCHLIST)
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Cannot evaluate from {current_status}"}

        assessments = self._load_assessments(ticker, opp_id, journal)
        rules = self._load_entry_rules(base_path)

        llm_eval = self._llm_evaluate(ticker, assessments, rules)
        all_rules_pass = llm_eval.get("all_rules_pass", False)
        recommendation = llm_eval.get("recommendation", "REJECT")

        decision_id = f"dec-{uuid4().hex[:8]}"
        decision = {
            "id": decision_id,
            "type": "BOARD_APPROVAL" if all_rules_pass else "BOARD_REJECTION",
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "APPROVED" if all_rules_pass else "REJECTED",
            "rules_evaluation": llm_eval.get("rules_detail", []),
            "rationale": llm_eval.get("rationale", ""),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        journal.save_decision(ticker, opp_id, decision)

        if all_rules_pass:
            new_status = OpportunityStatus.APPROVED
        else:
            new_status = OpportunityStatus.WATCHLIST

        opp["status"] = new_status.value
        opp["updated_at"] = datetime.now(UTC).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, current_status.value, new_status.value,
                                 cause=f"decision_board_{'approved' if all_rules_pass else 'rejected'}",
                                 worker="decision_board_worker")

        sqlite.log_event("decision_board:evaluated", {
            "opp_id": opp_id,
            "ticker": ticker,
            "decision": new_status.value,
            "rules_pass": all_rules_pass,
            "decision_id": decision_id,
        })

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "decision": new_status.value,
            "all_rules_pass": all_rules_pass,
            "recommendation": recommendation,
            "decision_id": decision_id,
            "rules_evaluated": len(llm_eval.get("rules_detail", [])),
        }

    def _load_assessments(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        ass_path = journal.opportunity_path(ticker, opp_id) / "assessments"
        if not ass_path.exists():
            return []
        import yaml
        assessments = []
        for f in sorted(ass_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    assessments.append(data)
        return assessments

    def _load_entry_rules(self, base_path: str) -> list[dict[str, Any]]:
        from pathlib import Path
        import yaml
        rules_path = Path(base_path) / "idos-config" / "rules" / "entry_rules.yml"
        if not rules_path.exists():
            return []
        with open(rules_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("rules", []) if data else []

    def _llm_evaluate(self, ticker: str, assessments: list[dict],
                       rules: list[dict]) -> dict[str, Any]:
        rules_text = "\n".join(
            f"- RULE {r.get('id','?')}: {r.get('description','')} "
            f"(condition: {r.get('condition','')}, priority: {r.get('priority','')})"
            for r in rules if r.get("active", True)
        )
        ass_text = "\n".join(
            f"- {a.get('engine','?')}: score={a.get('score','?')}, "
            f"confidence={a.get('confidence','?')}, findings={a.get('findings',[])}"
            for a in assessments
        )

        prompt = (
            f"Evalúa si {ticker} cumple las reglas de entrada del fondo.\n\n"
            f"Assessments disponibles:\n{ass_text}\n\n"
            f"Reglas de entrada:\n{rules_text}\n\n"
            "Para cada regla indica: rule_id, condition, passes (true/false), reason.\n"
            "Responde en JSON con:\n"
            '{{"all_rules_pass": bool, "recommendation": "APPROVE|REJECT|REVIEW", '
            '"rationale": "...", '
            '"rules_detail": [{{"rule_id": "...", "passes": bool, "reason": "..."}}]}}'
        )
        return self.llm.generate_structured(
            prompt=prompt,
            system_prompt=(
                "Eres el Decision Board de una Family Office. Evalúa fríamente "
                "si una oportunidad cumple TODAS las reglas de entrada. "
                "Si hay duda, responde REJECT. La preservación del capital es prioritaria."
            ),
            temperature=0.1,
        )
