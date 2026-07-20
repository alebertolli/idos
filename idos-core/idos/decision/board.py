from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.decision.orchestrator import DecisionProposal
from idos.models.enums import DecisionType
from idos.models.journal import Decision
from idos.data.journal import JournalRepository
from idos.events.bus import get_event_bus
from idos.events.types import Event
from idos.timezone import AR_TZ

@dataclass
class BoardResolution:
    approved: bool
    decision_id: str
    decision_type: DecisionType
    justification: str
    author: str = "human"
    resolved_at: str = ""

    def __post_init__(self):
        if not self.resolved_at:
            self.resolved_at = datetime.now(AR_TZ).isoformat()

class DecisionBoard:
    def __init__(self, journal_repo: JournalRepository | None = None):
        self.journal = journal_repo
        self._pending_proposals: list[DecisionProposal] = []

    @property
    def pending_proposals(self) -> list[DecisionProposal]:
        return list(self._pending_proposals)

    def submit(self, proposal: DecisionProposal):
        self._pending_proposals.append(proposal)
        bus = get_event_bus()
        bus.publish(Event(
            type="board:proposal_submitted",
            data={"opp_id": proposal.opportunity_id, "recommendation": proposal.recommendation},
        ))

    def review(self, proposal_index: int = -1) -> BoardResolution:
        if not self._pending_proposals:
            raise ValueError("No pending proposals")
        proposal = self._pending_proposals.pop(proposal_index)

        approved = proposal.recommendation == "APPROVE"
        if proposal.recommendation == "BLOCKED":
            approved = False

        decision = Decision(
            id=f"DEC-{datetime.now(AR_TZ).strftime('%Y%m%d%H%M%S')}",
            type=DecisionType.BUY if "buy" in proposal.type.lower() else DecisionType.HOLD,
            opportunity_id=proposal.opportunity_id,
            justification=proposal.reasoning,
            assessment_ids=[a.to_assessment_dict("")["id"] for a in proposal.assessments.values()],
            rules_applied=proposal.rules_passed + proposal.rules_failed,
            author="board",
        )

        if self.journal:
            self.journal.save_decision(
                proposal.opportunity_id.split("-")[0] if "-" in proposal.opportunity_id else "",
                proposal.opportunity_id,
                decision.model_dump(),
            )

        resolution = BoardResolution(
            approved=approved,
            decision_id=decision.id,
            decision_type=decision.type,
            justification=decision.justification,
        )

        bus = get_event_bus()
        bus.publish(Event(
            type="board:resolved",
            data={"decision_id": decision.id, "approved": approved},
        ))

        return resolution
