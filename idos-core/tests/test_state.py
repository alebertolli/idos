import pytest
from idos.state.machine import OpportunityStateMachine
from idos.models.enums import OpportunityStatus
from idos.core.errors import StateTransitionError


def test_valid_transitions():
    sm = OpportunityStateMachine()
    assert sm.can_transition(OpportunityStatus.SCREENED, OpportunityStatus.UNDER_RESEARCH)
    assert sm.can_transition(OpportunityStatus.SCREENED, OpportunityStatus.WATCHLIST)
    assert sm.can_transition(OpportunityStatus.WATCHLIST, OpportunityStatus.SCREENED)
    assert sm.can_transition(OpportunityStatus.WATCHLIST, OpportunityStatus.ARCHIVED)
    assert sm.can_transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.UNDER_RESEARCH)
    assert sm.can_transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.WATCHLIST)
    assert sm.can_transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.APPROVED)
    assert sm.can_transition(OpportunityStatus.APPROVED, OpportunityStatus.ENTRY_PENDING)
    assert sm.can_transition(OpportunityStatus.ENTRY_PENDING, OpportunityStatus.ACCUMULATING)
    assert sm.can_transition(OpportunityStatus.ACCUMULATING, OpportunityStatus.FULL_POSITION)
    assert sm.can_transition(OpportunityStatus.FULL_POSITION, OpportunityStatus.MONITORING)
    assert sm.can_transition(OpportunityStatus.MONITORING, OpportunityStatus.REDUCING)
    assert sm.can_transition(OpportunityStatus.MONITORING, OpportunityStatus.EXITED)
    assert sm.can_transition(OpportunityStatus.REDUCING, OpportunityStatus.EXITED)
    assert sm.can_transition(OpportunityStatus.REDUCING, OpportunityStatus.MONITORING)
    assert sm.can_transition(OpportunityStatus.EXITED, OpportunityStatus.POST_MORTEM)
    assert sm.can_transition(OpportunityStatus.POST_MORTEM, OpportunityStatus.ARCHIVED)


def test_discovered_no_automatic_transitions():
    sm = OpportunityStateMachine()
    assert sm.get_next_states(OpportunityStatus.DISCOVERED) == []


def test_invalid_transitions():
    sm = OpportunityStateMachine()
    assert not sm.can_transition(OpportunityStatus.SCREENED, OpportunityStatus.APPROVED)
    assert not sm.can_transition(OpportunityStatus.SCREENED, OpportunityStatus.ENTRY_PENDING)
    assert not sm.can_transition(OpportunityStatus.WATCHLIST, OpportunityStatus.UNDER_RESEARCH)
    assert not sm.can_transition(OpportunityStatus.WATCHLIST, OpportunityStatus.APPROVED)
    assert not sm.can_transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.ENTRY_PENDING)
    assert not sm.can_transition(OpportunityStatus.APPROVED, OpportunityStatus.UNDER_RESEARCH)


def test_transition_raises_error():
    sm = OpportunityStateMachine()
    with pytest.raises(StateTransitionError):
        sm.transition(OpportunityStatus.SCREENED, OpportunityStatus.APPROVED)


def test_screened_to_under_research():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.SCREENED, OpportunityStatus.UNDER_RESEARCH,
                      cause="scout passed", worker="universe_pipeline")
    assert t.from_status == OpportunityStatus.SCREENED
    assert t.to_status == OpportunityStatus.UNDER_RESEARCH


def test_screened_to_watchlist():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.SCREENED, OpportunityStatus.WATCHLIST,
                      cause="score below threshold", worker="monthly_evaluation")
    assert t.from_status == OpportunityStatus.SCREENED
    assert t.to_status == OpportunityStatus.WATCHLIST


def test_under_research_to_under_research():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.UNDER_RESEARCH,
                      cause="re-research forced", worker="ddd_pipeline")
    assert t.from_status == OpportunityStatus.UNDER_RESEARCH
    assert t.to_status == OpportunityStatus.UNDER_RESEARCH


def test_under_research_to_watchlist():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.WATCHLIST,
                      cause="board rejected", worker="decision_board_worker")
    assert t.from_status == OpportunityStatus.UNDER_RESEARCH
    assert t.to_status == OpportunityStatus.WATCHLIST


def test_watchlist_to_screened():
    sm = OpportunityStateMachine()
    t = sm.transition(OpportunityStatus.WATCHLIST, OpportunityStatus.SCREENED,
                      cause="score recovered above threshold", worker="monthly_evaluation")
    assert t.from_status == OpportunityStatus.WATCHLIST
    assert t.to_status == OpportunityStatus.SCREENED


def test_get_next_states():
    sm = OpportunityStateMachine()
    next_states = sm.get_next_states(OpportunityStatus.MONITORING)
    assert OpportunityStatus.REDUCING in next_states
    assert OpportunityStatus.EXITED in next_states
    next_states = sm.get_next_states(OpportunityStatus.SCREENED)
    assert OpportunityStatus.UNDER_RESEARCH in next_states
    assert OpportunityStatus.WATCHLIST in next_states
