import pytest
from idos.state.machine import OpportunityStateMachine
from idos.models.enums import OpportunityStatus
from idos.core.errors import StateTransitionError


def test_valid_transitions():
    sm = OpportunityStateMachine()
    assert sm.can_transition(OpportunityStatus.DISCOVERED, OpportunityStatus.SCREENED)
    assert sm.can_transition(OpportunityStatus.SCREENED, OpportunityStatus.WATCHLIST)
    assert sm.can_transition(OpportunityStatus.WATCHLIST, OpportunityStatus.UNDER_DEEP_DD)
    assert sm.can_transition(OpportunityStatus.UNDER_DEEP_DD, OpportunityStatus.APPROVED)
    assert sm.can_transition(OpportunityStatus.APPROVED, OpportunityStatus.ENTRY_PENDING)
    assert sm.can_transition(OpportunityStatus.ENTRY_PENDING, OpportunityStatus.ACCUMULATING)
    assert sm.can_transition(OpportunityStatus.FULL_POSITION, OpportunityStatus.MONITORING)
    assert sm.can_transition(OpportunityStatus.MONITORING, OpportunityStatus.REDUCING)
    assert sm.can_transition(OpportunityStatus.REDUCING, OpportunityStatus.EXITED)
    assert sm.can_transition(OpportunityStatus.EXITED, OpportunityStatus.POST_MORTEM)
    assert sm.can_transition(OpportunityStatus.POST_MORTEM, OpportunityStatus.ARCHIVED)


def test_invalid_transition():
    sm = OpportunityStateMachine()
    assert not sm.can_transition(OpportunityStatus.DISCOVERED, OpportunityStatus.APPROVED)
    assert not sm.can_transition(OpportunityStatus.DISCOVERED, OpportunityStatus.ARCHIVED)


def test_transition_raises_error():
    sm = OpportunityStateMachine()
    with pytest.raises(StateTransitionError):
        sm.transition(OpportunityStatus.DISCOVERED, OpportunityStatus.APPROVED)


def test_transition_creates_record():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.DISCOVERED, OpportunityStatus.SCREENED, cause="scout completed")
    assert t.from_status == OpportunityStatus.DISCOVERED
    assert t.to_status == OpportunityStatus.SCREENED
    assert t.cause == "scout completed"


def test_get_next_states():
    sm = OpportunityStateMachine()
    next_states = sm.get_next_states(OpportunityStatus.MONITORING)
    assert OpportunityStatus.REDUCING in next_states
    assert OpportunityStatus.EXITED in next_states
