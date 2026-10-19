from pathlib import Path
import yaml
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
    resolution = board.review(approved=True, reviewer="manager", justification="Validated research and valuation.")
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
    resolution = board.review(approved=False, reviewer="manager", justification="Rules block the proposal.")
    assert resolution.approved is False


def test_board_with_journal(tmp_path: Path):
    repo = JournalRepository(tmp_path)
    board = DecisionBoard(journal_repo=repo, ticker="AAPL")
    proposal = DecisionProposal(
        type="buy", opportunity_id="OPP-001",
        assessments={
            "TestEngine": AssessmentResult(engine="TestEngine", score=80)
        },
        rules_passed=["RULE-001"], rules_failed=[], conviction_score=80,
        recommendation="APPROVE",
    )
    board.submit(proposal)
    resolution = board.review(approved=True, reviewer="manager", justification="Validated research and valuation.")
    assert resolution.decision_id.startswith("DEC-")
    decision_path = repo.opportunity_path("AAPL", "OPP-001") / "decisions" / f"{resolution.decision_id}.yml"
    saved = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    assert saved["type"] == "BUY"
    assert saved["opportunity_id"] == "OPP-001"


def test_board_requires_explicit_attributed_manager_decision():
    board = DecisionBoard()
    board.submit(DecisionProposal(
        type="buy", opportunity_id="OPP-001", assessments={}, rules_passed=[],
        rules_failed=[], conviction_score=80, recommendation="APPROVE",
    ))
    try:
        board.review()
    except ValueError as exc:
        assert "explicit manager decision" in str(exc)
    else:
        raise AssertionError("Automated review must not approve a proposal")
    assert len(board.pending_proposals) == 1


def test_board_rejects_human_approval_when_rules_block_proposal():
    board = DecisionBoard()
    board.submit(DecisionProposal(
        type="buy", opportunity_id="OPP-001", assessments={}, rules_passed=[],
        rules_failed=["RULE-008"], conviction_score=80, recommendation="BLOCKED",
    ))
    try:
        board.review(approved=True, reviewer="manager", justification="I approve this candidate.")
    except ValueError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("Manager approval must not bypass failed authorization rules")
