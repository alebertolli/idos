from pathlib import Path
from datetime import date, timedelta

import yaml

from idos.decision.automatic_buylist import (
    authorize_buylist_if_eligible,
    revoke_buylist_on_thesis_invalidation,
)
from idos.decision.scenarios import scenario_fingerprint


def _seed_candidate(root: Path):
    opp_dir = root / "idos-journal/companies/NVDA/case_file/opportunities/OPP-NVDA"
    opp_dir.mkdir(parents=True)
    today = date.today()
    source_date = (today - timedelta(days=1)).isoformat()
    analysis = {
        "schema_version": "bear_bull_v2",
        "quantification_status": "validated",
        "as_of_date": today.isoformat(),
        "horizon_date": (today + timedelta(days=365)).isoformat(),
        "currency": "USD",
        "scenarios": [
            {"id": "BEAR", "target_price": 80, "rationale": "Demanda cae.", "key_assumptions": ["Demanda menor"], "falsifiers": ["Pedidos crecen"], "sources": [{"name": "Filing", "url": "https://example.com/bear", "as_of_date": source_date}]},
            {"id": "BASE", "target_price": 110, "rationale": "Crecimiento moderado.", "key_assumptions": ["Márgenes estables"], "falsifiers": ["Márgenes caen"], "sources": [{"name": "Filing", "url": "https://example.com/base", "as_of_date": source_date}]},
            {"id": "BULL", "target_price": 150, "rationale": "Adopción acelera.", "key_assumptions": ["Mayor demanda"], "falsifiers": ["Cancelaciones"], "sources": [{"name": "Filing", "url": "https://example.com/bull", "as_of_date": source_date}]},
        ],
    }
    report = {
        "scenario_analysis": analysis,
        "research_input_snapshot": {
            "scenario_market_evidence": {
                "current_quote": {"sources": [{"url": "https://example.com/bear"}]},
                "analyst_target_consensus": {"sources": [{"url": "https://example.com/base"}, {"url": "https://example.com/bull"}]},
            },
        },
    }
    proposal = {
        "opportunity_id": "OPP-NVDA",
        "recommendation": "PENDING_REVIEW",
        "rules_passed": ["RULE-001", "RULE-003", "RULE-004", "RULE-005", "RULE-008", "RULE-010"],
        "rules_failed": [],
        "scenario_hash": scenario_fingerprint(analysis),
        "conviction_score": 69,
        "generated_at": "2026-11-19T12:00:00-03:00",
        "status": "PENDING_AUTOMATED_AUTHORIZATION",
    }
    opportunity = {
        "id": "OPP-NVDA", "ticker": "NVDA", "status": "UNDER_DEEP_DD",
        "strategy_id": "MULTIBAGGERS", "entry_policy": "MANUAL_REVIEW",
        "approved_for_buylist": False, "thesis_active": True,
        "intrinsic_value": 246.67, "current_price": 215.52,
        "conviction": {"overall": 69, "intrinsic_value": 246.67, "current_price": 215.52},
    }
    for name, data in (("ddd_report.yml", report), ("decision_proposal.yml", proposal), ("opportunity.yml", opportunity)):
        (opp_dir / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    config = root / "idos-config"
    config.mkdir()
    (config / "portfolio.yml").write_text("margin_of_safety: 30\n", encoding="utf-8")
    (config / "strategies.yml").write_text(
        "strategies:\n  MULTIBAGGERS:\n    parameters:\n      position_limit_pct: 1.0\n", encoding="utf-8",
    )
    return opp_dir, proposal, opportunity


def test_all_authorization_rules_auto_admit_to_buylist_without_creating_position(tmp_path):
    opp_dir, proposal, opportunity = _seed_candidate(tmp_path)

    result = authorize_buylist_if_eligible(
        tmp_path, "NVDA", "OPP-NVDA", proposal, opportunity,
        {"RULE-001", "RULE-003", "RULE-004", "RULE-005", "RULE-008", "RULE-010"},
    )

    assert result["approved"] is True
    saved_proposal = yaml.safe_load((opp_dir / "decision_proposal.yml").read_text(encoding="utf-8"))
    resolution = yaml.safe_load((opp_dir / "board_resolution.yml").read_text(encoding="utf-8"))
    saved_opportunity = yaml.safe_load((opp_dir / "opportunity.yml").read_text(encoding="utf-8"))
    buylist = yaml.safe_load((tmp_path / "idos-journal/portfolio/buylist.yml").read_text(encoding="utf-8"))
    entry = buylist["entries"][0]
    assert saved_proposal["status"] == "AUTO_APPROVED"
    assert resolution["status"] == "AUTO_APPROVED"
    assert resolution["author"] == "idos:auto-authorization"
    assert saved_opportunity["approved_for_buylist"] is True
    assert entry["ticker"] == "NVDA"
    assert entry["authorization_mode"] == "automatic_rules"
    assert entry["max_position_pct"] == 1.0
    assert saved_opportunity["status"] == "UNDER_DEEP_DD"
    assert not (tmp_path / "idos-journal/portfolio/positions").exists()
    assert (opp_dir / "decisions" / f"{result['decision_id']}.yml").is_file()


def test_missing_authorization_rule_fails_closed(tmp_path):
    opp_dir, proposal, opportunity = _seed_candidate(tmp_path)
    proposal["rules_passed"].remove("RULE-010")
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    result = authorize_buylist_if_eligible(
        tmp_path, "NVDA", "OPP-NVDA", proposal, opportunity,
        {"RULE-001", "RULE-003", "RULE-004", "RULE-005", "RULE-008", "RULE-010"},
    )

    assert result == {"approved": False, "reason": "authorization_rules_not_all_passed"}
    assert not (tmp_path / "idos-journal/portfolio/buylist.yml").exists()


def test_thesis_invalidation_removes_only_matching_buylist_entry_and_preserves_history(tmp_path):
    opp_dir, _, _ = _seed_candidate(tmp_path)
    proposal_path = opp_dir / "decision_proposal.yml"
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal["status"] = "AUTO_APPROVED"
    proposal_path.write_text(yaml.safe_dump(proposal), encoding="utf-8")
    resolution_path = opp_dir / "board_resolution.yml"
    resolution_path.write_text(yaml.safe_dump({"approved": True, "status": "AUTO_APPROVED", "author": "idos:auto-authorization"}), encoding="utf-8")
    opportunity_path = opp_dir / "opportunity.yml"
    opportunity = yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))
    opportunity["approved_for_buylist"] = True
    opportunity_path.write_text(yaml.safe_dump(opportunity), encoding="utf-8")
    decisions = opp_dir / "decisions"
    decisions.mkdir()
    prior = decisions / "AUTO-PRIOR.yml"
    prior.write_text("status: AUTO_APPROVED\n", encoding="utf-8")
    buylist_path = tmp_path / "idos-journal/portfolio/buylist.yml"
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [
        {"ticker": "NVDA", "opp_id": "OPP-NVDA"},
        {"ticker": "NVDA", "opp_id": "OPP-OTHER"},
        {"ticker": "MSFT", "opp_id": "OPP-MSFT"},
    ]}), encoding="utf-8")
    position_path = tmp_path / "idos-journal/portfolio/positions/NVDA.yml"
    position_path.parent.mkdir(parents=True, exist_ok=True)
    position_path.write_text("ticker: NVDA\nshares: 1\n", encoding="utf-8")

    removed = revoke_buylist_on_thesis_invalidation(
        tmp_path, "NVDA", "OPP-NVDA", invalidated_at="2026-11-20T12:00:00-03:00",
        reason="La hipótesis principal fue falsada.",
    )

    assert removed is True
    entries = yaml.safe_load(buylist_path.read_text(encoding="utf-8"))["entries"]
    assert entries == [
        {"ticker": "NVDA", "opp_id": "OPP-OTHER"},
        {"ticker": "MSFT", "opp_id": "OPP-MSFT"},
    ]
    assert yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))["approved_for_buylist"] is False
    assert yaml.safe_load(resolution_path.read_text(encoding="utf-8"))["status"] == "REVOKED_THESIS_INVALIDATED"
    assert prior.read_text(encoding="utf-8") == "status: AUTO_APPROVED\n"
    assert position_path.exists()
    assert list(decisions.glob("AUTO-REVOKE-*.yml"))
