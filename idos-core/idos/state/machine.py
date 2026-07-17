from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any
from idos.models.enums import OpportunityStatus
from idos.core.errors import StateTransitionError


@dataclass
class Transition:
    from_status: OpportunityStatus
    to_status: OpportunityStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cause: str = ""
    worker: str = "system"


class StateMachine:
    def __init__(self, allowed_transitions: dict[OpportunityStatus, list[OpportunityStatus]]):
        self._allowed = allowed_transitions

    def can_transition(self, current: OpportunityStatus, target: OpportunityStatus) -> bool:
        return target in self._allowed.get(current, [])

    def transition(self, current: OpportunityStatus, target: OpportunityStatus, cause: str = "", worker: str = "system") -> Transition:
        if not self.can_transition(current, target):
            raise StateTransitionError(f"Cannot transition from {current} to {target}")
        return Transition(
            from_status=current,
            to_status=target,
            cause=cause,
            worker=worker,
        )


class OpportunityStateMachine(StateMachine):
    _transitions: dict[OpportunityStatus, list[OpportunityStatus]] = {
        OpportunityStatus.DISCOVERED: [OpportunityStatus.SCREENED],
        OpportunityStatus.SCREENED: [OpportunityStatus.WATCHLIST, OpportunityStatus.ARCHIVED],
        OpportunityStatus.WATCHLIST: [OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.UNDER_DEEP_DD, OpportunityStatus.ARCHIVED],
        OpportunityStatus.UNDER_RESEARCH: [OpportunityStatus.UNDER_DEEP_DD, OpportunityStatus.WATCHLIST],
        OpportunityStatus.UNDER_DEEP_DD: [OpportunityStatus.APPROVED, OpportunityStatus.WATCHLIST],
        OpportunityStatus.APPROVED: [OpportunityStatus.ENTRY_PENDING, OpportunityStatus.WATCHLIST],
        OpportunityStatus.ENTRY_PENDING: [OpportunityStatus.ACCUMULATING, OpportunityStatus.WATCHLIST],
        OpportunityStatus.ACCUMULATING: [OpportunityStatus.FULL_POSITION, OpportunityStatus.EXITED, OpportunityStatus.MONITORING],
        OpportunityStatus.FULL_POSITION: [OpportunityStatus.MONITORING, OpportunityStatus.REDUCING],
        OpportunityStatus.MONITORING: [OpportunityStatus.REDUCING, OpportunityStatus.EXITED, OpportunityStatus.FULL_POSITION],
        OpportunityStatus.REDUCING: [OpportunityStatus.EXITED, OpportunityStatus.MONITORING],
        OpportunityStatus.EXITED: [OpportunityStatus.POST_MORTEM],
        OpportunityStatus.POST_MORTEM: [OpportunityStatus.ARCHIVED],
        OpportunityStatus.ARCHIVED: [],
    }

    def __init__(self):
        super().__init__(self._transitions)

    def get_next_states(self, current: OpportunityStatus) -> list[OpportunityStatus]:
        return self._allowed.get(current, [])
