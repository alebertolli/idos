import tempfile
from pathlib import Path
from idos.decision.board import DecisionBoard
from idos.decision.orchestrator import DecisionProposal
from idos.decision.engines.base import AssessmentResult
from idos.data.journal import JournalRepository


def test_board_submit_and_review():
    board = DecisionBoard()
    proposal = DecisionProposal(
        type="buy",
        opportunity_id="OPP-2026-001",
        assessments={
            "TestEngine": AssessmentResult(engine="TestEngine", score=85, confidence="HIGH")
        },
        rules_passed=["RULE-001"],
        rules_failed=[],
        conviction_score=85,
        recommendation="APPROVE",
    )
    board.submit(proposal)
    assert len(board.pending_proposals) == 1
    resolution = board.review()
    assert resolution.approved is True
    assert len(board.pending_proposals) == 0


def test_board_rejects_blocked():
    board = DecisionBoard()
    proposal = DecisionProposal(
        type="buy", opportunity_id="OPP-001",
        assessments={}, rules_passed=[], rules_failed=["RULE-006"],
        conviction_score=50, recommendation="BLOCKED",
    )
    board.submit(proposal)
    resolution = board.review()
    assert resolution.approved is False


def test_board_with_journal():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JournalRepository(Path(tmp))
        board = DecisionBoard(journal_repo=repo)
        proposal = DecisionProposal(
            type="buy", opportunity_id="OPP-001",
            assessments={
                "TestEngine": AssessmentResult(engine="TestEngine", score=80)
            },
            rules_passed=["RULE-001"], rules_failed=[], conviction_score=80,
            recommendation="APPROVE",
        )
        board.submit(proposal)
        resolution = board.review()
        assert resolution.decision_id.startswith("DEC-")
