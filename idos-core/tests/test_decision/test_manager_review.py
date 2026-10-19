from pathlib import Path

import pytest
import yaml

from idos.decision.proposal_review import decision_proposal_fingerprint
from scripts.review_decision import record_decision_review


def _seed_fundamental_case(base_path: Path, *, recommendation="APPROVE", rules_failed=None):
    opp_dir = base_path / "idos-journal/companies/TEST/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    proposal = {
        "opportunity_id": "OPP-1",
        "recommendation": recommendation,
        "rules_passed": ["RULE-008", "RULE-010"],
        "rules_failed": rules_failed or [],
        "conviction_score": 82,
        "generated_at": "2026-10-19T12:00:00-03:00",
        "status": "PENDING_HUMAN_REVIEW",
    }
    opportunity = {
        "id": "OPP-1", "ticker": "TEST", "status": "UNDER_DEEP_DD",
        "research_profile": "strategic",
        "current_price": 100,
        "intrinsic_value": 125,
        "conviction": {"overall": 82, "current_price": 100, "intrinsic_value": 125},
    }
    analysis = {
        "schema_version": "bear_base_bull_v1",
        "as_of_date": "2026-10-19",
        "horizon_date": "2027-10-19",
        "currency": "USD",
        "scenarios": [
            {"id": "BEAR", "probability_pct": 25, "target_price": 80, "sources": [{"name": "Filing", "url": "https://example.com/bear", "as_of_date": "2026-10-18"}]},
            {"id": "BASE", "probability_pct": 50, "target_price": 110, "sources": [{"name": "Filing", "url": "https://example.com/base", "as_of_date": "2026-10-18"}]},
            {"id": "BULL", "probability_pct": 25, "target_price": 150, "sources": [{"name": "Filing", "url": "https://example.com/bull", "as_of_date": "2026-10-18"}]},
        ],
    }
    review = {
        "status": "approved",
        "scenario_hash": "",
        "reviewed_by": "github-manager",
        "reviewed_at": "2026-10-19T12:00:00-03:00",
        "note": "Reviewed evidence and valuation assumptions.",
    }
    from idos.decision.scenarios import scenario_fingerprint
    review["scenario_hash"] = scenario_fingerprint(analysis)
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump(proposal, allow_unicode=True), encoding="utf-8")
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8")
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump({"scenario_analysis": analysis}, allow_unicode=True), encoding="utf-8")
    (opp_dir / "scenario_review.yml").write_text(yaml.safe_dump(review, allow_unicode=True), encoding="utf-8")
    return opp_dir, proposal


def test_manager_approval_requires_current_assessment_and_scenario_and_writes_audit(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    proposal_path = opp_dir / "decision_proposal.yml"
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    current_hash = decision_proposal_fingerprint(proposal)

    resolution_path, decision_path = record_decision_review(
        tmp_path, "TEST", "OPP-1", current_hash, "approved", "github-manager",
        "Reviewed thesis, sources, downside and allocation boundary.",
    )

    resolution = yaml.safe_load(resolution_path.read_text(encoding="utf-8"))
    saved_proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    opportunity = yaml.safe_load((opp_dir / "opportunity.yml").read_text(encoding="utf-8"))
    assert resolution["approved"] is True
    assert resolution["proposal_hash"] == current_hash
    assert resolution["author"] == "github-manager"
    assert decision_path.is_file()
    assert saved_proposal["status"] == "MANAGER_APPROVED"
    assert decision_proposal_fingerprint(saved_proposal) == current_hash
    assert opportunity["status"] == "UNDER_DEEP_DD"
    assert opportunity["approved_for_buylist"] is True
    buylist = yaml.safe_load((tmp_path / "idos-journal/portfolio/buylist.yml").read_text(encoding="utf-8"))
    assert buylist["entries"][0]["ticker"] == "TEST"
    assert not (tmp_path / "idos-journal/portfolio/positions").exists()

    with pytest.raises(ValueError, match="already has a manager decision"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", current_hash, "approved", "github-manager",
            "Reviewed thesis, sources, downside and allocation boundary.",
        )


def test_manager_approval_rejects_stale_hash_or_failed_gate(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    with pytest.raises(ValueError, match="stale"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", "0" * 64, "approved", "github-manager",
            "Reviewed thesis, sources, downside and allocation boundary.",
        )

    proposal["rules_failed"] = ["RULE-008"]
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump(proposal), encoding="utf-8")
    with pytest.raises(ValueError, match="every authorization rule"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", decision_proposal_fingerprint(proposal),
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.",
        )
    assert not (opp_dir / "board_resolution.yml").exists()


def test_manager_cannot_approve_proposal_invalidated_by_new_research(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    proposal["status"] = "INVALIDATED_BY_NEW_RESEARCH"
    proposal_path = opp_dir / "decision_proposal.yml"
    proposal_path.write_text(yaml.safe_dump(proposal), encoding="utf-8")

    with pytest.raises(ValueError, match="invalidated by newer Research"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", decision_proposal_fingerprint(proposal),
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.",
        )
