"""Deprecated compatibility shim for the retired automatic Decision Board.

Manager decisions are recorded through the authenticated Decision Review flow.
This worker intentionally performs no assessment, persistence, or transition.
"""

from typing import Any

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


class DecisionBoardWorker(BaseWorker):
    """Return a safe skip for legacy callers without changing opportunity state."""

    name = "decision_board_worker"

    def run(self, context: dict[str, Any]) -> WorkerResult:
        return WorkerResult(
            status=WorkerStatus.SKIPPED,
            worker=self.name,
            output={
                "status": "skipped",
                "reason": "legacy_automatic_decision_disabled",
                "message": (
                    "Use the deterministic Assessment proposal and authenticated "
                    "Decision Review flow for a manager decision."
                ),
                "ticker": str(context.get("ticker", "")).upper().strip(),
                "opp_id": str(context.get("opp_id", "")).strip(),
            },
        )
