from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from idos.decision.proposal_review import decision_proposal_fingerprint
from scripts.review_decision import record_decision_review


AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
TODAY = datetime.now(AR_TZ).date()
SOURCE_DATE = (TODAY - timedelta(days=1)).isoformat()
REVIEWED_AT = datetime.combine(TODAY, datetime.min.time(), tzinfo=AR_TZ).replace(hour=12).isoformat()


def _seed_fundamental_case(base_path: Path, *, recommendation="APPROVE", rules_failed=None):
    opp_dir = base_path / "idos-journal/companies/TEST/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    proposal = {
        "opportunity_id": "OPP-1",
        "recommendation": recommendation,
        "rules_passed": ["RULE-008", "RULE-010"],
        "rules_failed": rules_failed or [],
        "scenario_hash": None,
        "conviction_score": 82,
        "generated_at": REVIEWED_AT,
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
        "as_of_date": TODAY.isoformat(),
        "horizon_date": (TODAY + timedelta(days=365)).isoformat(),
        "currency": "USD",
        "scenarios": [
            {"id": "BEAR", "probability_pct": 25, "target_price": 80, "sources": [{"name": "Filing", "url": "https://example.com/bear", "as_of_date": SOURCE_DATE}]},
            {"id": "BASE", "probability_pct": 50, "target_price": 110, "sources": [{"name": "Filing", "url": "https://example.com/base", "as_of_date": SOURCE_DATE}]},
            {"id": "BULL", "probability_pct": 25, "target_price": 150, "sources": [{"name": "Filing", "url": "https://example.com/bull", "as_of_date": SOURCE_DATE}]},
        ],
    }
    review = {
        "status": "approved",
        "scenario_hash": "",
        "reviewed_by": "github-manager",
        "reviewed_at": REVIEWED_AT,
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    from idos.decision.scenarios import scenario_fingerprint
    review["scenario_hash"] = scenario_fingerprint(analysis)
    proposal["scenario_hash"] = review["scenario_hash"]
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump(proposal, allow_unicode=True), encoding="utf-8")
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8")
    report = {
        "scenario_analysis": analysis,
        "research_input_snapshot": {
            "scenario_market_evidence": {
                "current_quote": {"sources": [{"url": "https://example.com/bear"}]},
                "analyst_target_consensus": {
                    "sources": [{"url": "https://example.com/base"}, {"url": "https://example.com/bull"}],
                },
            },
        },
    }
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")
    return opp_dir, proposal


def test_manager_approval_requires_current_assessment_and_scenario_and_writes_audit(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    proposal_path = opp_dir / "decision_proposal.yml"
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    current_hash = decision_proposal_fingerprint(proposal)

    resolution_path, decision_path = record_decision_review(
        tmp_path, "TEST", "OPP-1", current_hash, "approved", "github-manager",
        "Reviewed thesis, sources, downside and allocation boundary.", True,
    )

    resolution = yaml.safe_load(resolution_path.read_text(encoding="utf-8"))
    saved_proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    opportunity = yaml.safe_load((opp_dir / "opportunity.yml").read_text(encoding="utf-8"))
    assert resolution["approved"] is True
    assert resolution["proposal_hash"] == current_hash
    assert resolution["author"] == "github-manager"
    assert resolution["scenario_hash"] == proposal["scenario_hash"]
    assert resolution["sources_verified"] is True
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
            "Reviewed thesis, sources, downside and allocation boundary.", True,
        )


def test_manager_approval_rejects_stale_hash_or_failed_gate(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    with pytest.raises(ValueError, match="stale"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", "0" * 64, "approved", "github-manager",
            "Reviewed thesis, sources, downside and allocation boundary.", True,
        )

    proposal["rules_failed"] = ["RULE-008"]
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump(proposal), encoding="utf-8")
    with pytest.raises(ValueError, match="every authorization rule"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", decision_proposal_fingerprint(proposal),
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.", True,
        )
    assert not (opp_dir / "board_resolution.yml").exists()


def test_manager_approval_rejects_scenario_source_absent_from_research_evidence(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    report_path = opp_dir / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["research_input_snapshot"]["scenario_market_evidence"]["analyst_target_consensus"]["sources"].pop()
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Current Bear/Base/Bull scenarios are invalid"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", decision_proposal_fingerprint(proposal),
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.", True,
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
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.", True,
        )


def test_manager_approval_confirms_sources_inside_board_review(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    proposal_hash = decision_proposal_fingerprint(proposal)

    with pytest.raises(ValueError, match="fuentes y sus fechas"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", proposal_hash, "approved", "github-manager",
            "Reviewed thesis, sources, downside and allocation boundary.", False,
        )

    assert not (opp_dir / "board_resolution.yml").exists()
    assert not (tmp_path / "idos-journal/portfolio/buylist.yml").exists()


def test_manager_approval_rejects_scenario_hash_changed_after_assessment(tmp_path):
    opp_dir, proposal = _seed_fundamental_case(tmp_path)
    report_path = opp_dir / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["scenario_analysis"]["scenarios"][2]["target_price"] = 151
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the assessed proposal"):
        record_decision_review(
            tmp_path, "TEST", "OPP-1", decision_proposal_fingerprint(proposal),
            "approved", "github-manager", "Reviewed thesis, sources, downside and allocation boundary.", True,
        )
    assert not (opp_dir / "board_resolution.yml").exists()


def test_manager_review_preserves_identity_and_path_validation(tmp_path):
    _, proposal = _seed_fundamental_case(tmp_path)
    proposal_hash = decision_proposal_fingerprint(proposal)
    note = "Reviewed thesis, sources, downside and allocation boundary."

    with pytest.raises(ValueError, match="Authenticated reviewer identity"):
        record_decision_review(tmp_path, "TEST", "OPP-1", proposal_hash, "approved", " ", note, True)
    with pytest.raises(ValueError, match="Opportunity id"):
        record_decision_review(tmp_path, "TEST", "../private", proposal_hash, "approved", "manager", note, True)


def test_decision_review_workflow_can_record_the_board_decision_on_main():
    workflow = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "decision-review.yml"
    source = workflow.read_text(encoding="utf-8")

    assert "if: github.ref != 'refs/heads/main'" not in source
    assert 'git push origin "HEAD:${GITHUB_REF_NAME}"' in source
