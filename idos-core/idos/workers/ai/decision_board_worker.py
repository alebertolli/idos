from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.models.knowledge import Rule
from idos.rules.engine import RulesEngine
from idos.rules.evaluators import register_default_rules
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

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
        self.rules_engine = RulesEngine()
        register_default_rules(self.rules_engine)

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
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Cannot evaluate from {current_status}"}

        assessments = self._load_assessments(ticker, opp_id, journal)
        rules = self._load_entry_rules(base_path)
        assessment_scores = {a.get("engine", "unknown"): a.get("score", 0) for a in assessments}
        conviction = opp.get("conviction", {})

        context_for_rules = {
            "assessments": {
                "business_quality": conviction.get("business", assessment_scores.get("ResearchWorker", 70)),
                "valuation": assessment_scores.get("ValuationEngine", 70),
                "rerating": assessment_scores.get("ReratingEngine", 70),
                "risk": assessment_scores.get("RiskEngine", 70),
            },
            "conviction": {"overall": conviction.get("overall", 70)},
            "portfolio": {"position_weight": 0, "sector_exposure": 0},
            "opportunity": {"asymmetry_ratio": 3.0},
        }

        # Build RulesEngine from YAML config, using registered evaluators
        local_engine = RulesEngine()
        for r in rules:
            if not r.get("active", True):
                continue
            rule_id = r["id"]
            fn = self.rules_engine._rule_fns.get(rule_id)
            if fn:
                local_engine.register_rule(
                    Rule(id=rule_id, description=r.get("description", ""),
                         priority=r.get("priority", 50), condition=r.get("condition", ""),
                         action=r.get("action", "PASS")),
                    fn,
                )

        rule_results = []
        for rule in local_engine._rules:
            result = local_engine.evaluate(rule.id, context_for_rules)
            rule_results.append(result)

        rules_passed = [r.rule_id for r in rule_results if r.passed]
        rules_failed = [r.rule_id for r in rule_results if not r.passed]
        all_rules_pass = len(rules_failed) == 0

        # LLM evaluation for explicability (secondary)
        llm_eval = self._llm_evaluate(ticker, assessments, rules)
        recommendation = llm_eval.get("recommendation", "APPROVE" if all_rules_pass else "REJECT")
        rationale = llm_eval.get("rationale", "")

        decision_id = f"dec-{uuid4().hex[:8]}"
        decision = {
            "id": decision_id,
            "type": "BOARD_APPROVAL" if all_rules_pass else "BOARD_REJECTION",
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "APPROVED" if all_rules_pass else "REJECTED",
            "rules_evaluation": {
                "deterministic": {"passed": rules_passed, "failed": rules_failed},
                "llm": llm_eval.get("rules_detail", []),
            },
            "rationale": rationale,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_decision(ticker, opp_id, decision)

        new_status = OpportunityStatus.APPROVED if all_rules_pass else OpportunityStatus.WATCHLIST

        opp["status"] = new_status.value
        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, current_status.value, new_status.value,
                                 cause=f"decision_board_{'approved' if all_rules_pass else 'rejected'}",
                                 worker="decision_board_worker")

        sqlite.log_event("decision_board:evaluated", {
            "opp_id": opp_id,
            "ticker": ticker,
            "decision": new_status.value,
            "rules_pass": all_rules_pass,
            "deterministic_passed": rules_passed,
            "deterministic_failed": rules_failed,
            "decision_id": decision_id,
        })

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "decision": new_status.value,
            "all_rules_pass": all_rules_pass,
            "deterministic_passed": rules_passed,
            "deterministic_failed": rules_failed,
            "recommendation": recommendation,
            "decision_id": decision_id,
            "rules_evaluated": len(rule_results),
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
