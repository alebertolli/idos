from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.learning.post_mortem import build_post_mortem_analysis
from idos.models.enums import OpportunityStatus
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class PostMortemWorker(BaseWorker):
    """Generates post-mortem analysis after an opportunity is exited.

    Triggers: after EXITED status.
    Transitions: EXITED -> POST_MORTEM. Archival requires human approval.
    """
    name = "post_mortem_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
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
        hypotheses = journal.load_hypotheses(ticker, opp_id)
        wyckoff_analyses = self._load_wyckoff_analyses(ticker, opp_id, journal)
        entry_snapshot = journal.load_entry_snapshot(ticker, opp_id)

        post_mortem = build_post_mortem_analysis(
            decisions=decisions,
            assessments=assessments,
            position=position,
            exit_reason=exit_reason,
            wyckoff_analyses=wyckoff_analyses,
            hypotheses=hypotheses,
            entry_snapshot=entry_snapshot,
        )

        pm_id = f"pm-{uuid4().hex[:8]}"
        pm_record = {
            "id": pm_id,
            "ticker": ticker,
            "opp_id": opp_id,
            "strategy_id": opp.get("strategy_id", "COMPOUNDER"),
            "strategy_version": opp.get("strategy_version", "legacy-compatible"),
            "exit_reason": exit_reason,
            "analysis": post_mortem,
            "review_status": "PENDING_REVIEW",
            "recommendations": [],
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }

        # Post-portfolio analysis must never enter the public, tracked journal.
        pm_path = bp / "private-data" / "learning" / "post_mortems"
        pm_path.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(pm_path / f"{pm_id}.yml", "w", encoding="utf-8") as f:
            yaml.dump(pm_record, f, default_flow_style=False, allow_unicode=True)

        opp["status"] = OpportunityStatus.POST_MORTEM.value
        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, current_status.value, "POST_MORTEM",
                                 cause="post_mortem_generated", worker="post_mortem_worker")

        sqlite.log_event("post_mortem:completed", {
            "opp_id": opp_id, "ticker": ticker,
            "exit_reason": exit_reason,
            "pm_id": pm_id,
            "archived": False,
        })

        wyckoff_accuracy = post_mortem.get("wyckoff_accuracy", "no_evaluada")

        hypothesis_stats = self._hypothesis_stats(hypotheses)

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "archived": False,
            "pm_id": pm_id,
            "exit_reason": exit_reason,
            "lessons": post_mortem.get("observations", []),
            "wyckoff_accuracy": wyckoff_accuracy,
            "wyckoff_lessons": post_mortem.get("wyckoff_lessons", []),
            "hypotheses": hypothesis_stats,
            "learning_status": "PENDING_REVIEW",
        }

    def _hypothesis_stats(self, hypotheses: list[dict]) -> dict[str, Any]:
        if not hypotheses:
            return {"count": 0, "predictions_evaluated": 0, "predictions_met": 0}
        evaluated = 0
        met = 0
        for h in hypotheses:
            for p in h.get("predictions", []):
                if p.get("met") is not None:
                    evaluated += 1
                    if p.get("met"):
                        met += 1
        stats = {
            "count": len(hypotheses),
            "predictions_evaluated": evaluated,
            "predictions_met": met,
        }
        if evaluated:
            stats["predictions_met_pct"] = round(met / evaluated * 100, 1)
        return stats

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

    def _load_wyckoff_analyses(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        w_path = journal.opportunity_path(ticker, opp_id) / "wyckoff"
        if not w_path.exists():
            return []
        import yaml
        analyses = []
        for f in sorted(w_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    analyses.append(data)
        return analyses
