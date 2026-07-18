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


class PostMortemWorker(BaseWorker):
    """Generates post-mortem analysis after an opportunity is exited.

    Triggers: after EXITED status.
    Transitions: EXITED -> POST_MORTEM -> ARCHIVED.
    """
    name = "post_mortem_worker"

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
        exit_reason = context.get("exit_reason", "unknown")
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
        if not self.state_machine.can_transition(current_status, OpportunityStatus.POST_MORTEM):
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Cannot run post-mortem from {current_status}"}

        decisions = self._load_decisions(ticker, opp_id, journal)
        assessments = self._load_assessments(ticker, opp_id, journal)
        position = journal.load_position(ticker)

        post_mortem = self._llm_post_mortem(ticker, decisions, assessments, position, exit_reason)

        pm_id = f"pm-{uuid4().hex[:8]}"
        pm_record = {
            "id": pm_id,
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": exit_reason,
            "analysis": post_mortem,
            "generated_at": datetime.now(UTC).isoformat(),
        }

        pm_path = journal.opportunity_path(ticker, opp_id) / "post_mortem"
        pm_path.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(pm_path / f"{pm_id}.yml", "w", encoding="utf-8") as f:
            yaml.dump(pm_record, f, default_flow_style=False, allow_unicode=True)

        opp["status"] = OpportunityStatus.POST_MORTEM.value
        opp["updated_at"] = datetime.now(UTC).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, current_status.value, "POST_MORTEM",
                                 cause="post_mortem_generated", worker="post_mortem_worker")

        if self.state_machine.can_transition(OpportunityStatus.POST_MORTEM, OpportunityStatus.ARCHIVED):
            opp["status"] = OpportunityStatus.ARCHIVED.value
            opp["updated_at"] = datetime.now(UTC).isoformat()
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, "POST_MORTEM", "ARCHIVED",
                                     cause="post_mortem_approved", worker="post_mortem_worker")

        sqlite.log_event("post_mortem:completed", {
            "opp_id": opp_id, "ticker": ticker,
            "exit_reason": exit_reason,
            "pm_id": pm_id,
            "archived": True,
        })

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "archived": True,
            "pm_id": pm_id,
            "exit_reason": exit_reason,
            "lessons": post_mortem.get("lessons_learned", []),
        }

    def _load_decisions(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        dec_path = journal.opportunity_path(ticker, opp_id) / "decisions"
        if not dec_path.exists():
            return []
        import yaml
        decisions = []
        for f in sorted(dec_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    decisions.append(data)
        return decisions

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

    def _llm_post_mortem(self, ticker: str, decisions: list[dict],
                          assessments: list[dict], position: dict | None,
                          exit_reason: str) -> dict[str, Any]:
        prompt = (
            f"Genera un Post-Mortem de inversión para {ticker}.\n\n"
            f"Razón de salida: {exit_reason}\n\n"
            f"Decisiones registradas:\n"
        )
        for d in decisions:
            prompt += f"- {d.get('type','?')}: {d.get('rationale','')[:200]}\n"

        prompt += f"\nAssessments:\n"
        for a in assessments:
            prompt += f"- {a.get('engine','?')} score={a.get('score','?')}: {a.get('findings',[])}\n"

        if position:
            prompt += (
                f"\nPosición: entrada a ${position.get('avg_entry_price',0)}, "
                f"peso {position.get('weight_pct',0)}%\n"
            )

        prompt += (
            "\nResponde en JSON:\n"
            '{{"exit_analysis": "...", "thesis_was_correct": true|false, '
            '"what_went_wrong": ["..."], "what_went_right": ["..."], '
            '"lessons_learned": ["..."], '
            '"methodological_errors": ["..."], "biases_detected": ["..."], '
            '"would_invest_again": true|false}}'
        )

        return self.llm.generate_structured(
            prompt=prompt,
            system_prompt=(
                "Eres un analista de learning & improvement para una Family Office. "
                "Sé brutalmente honesto en la autopsia de la inversión. "
                "El objetivo es aprender, no justificar."
            ),
            temperature=0.3,
        )
