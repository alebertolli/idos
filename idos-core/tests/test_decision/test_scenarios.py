from datetime import date

import pytest
import yaml

from idos.decision.scenarios import (
    calculate_scenario_asymmetry,
    scenario_fingerprint,
    validate_scenario_analysis,
    validate_scenario_review,
)
from idos.decision.assessment_pipeline import _calculate_report_asymmetry, _eval_asymmetry
from scripts.review_scenario import record_scenario_review


def scenario_set():
    return {
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


def test_valid_bear_base_bull_contract_and_expected_asymmetry():
    analysis = scenario_set()

    assert validate_scenario_analysis(analysis, today=date(2026, 10, 19)) == []
    asymmetry = calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="USD")
    assert asymmetry["validation_status"] == "validated"
    assert asymmetry["authorization_eligible"] is False
    assert asymmetry["upside_esperado_pct"] == 17.5
    assert asymmetry["downside_esperado_pct"] == -5
    assert asymmetry["benefit_risk_ratio"] == 3.5


def test_invalid_scenario_contract_fails_closed():
    analysis = scenario_set()
    analysis["scenarios"][0]["probability_pct"] = 30
    analysis["scenarios"][1]["sources"][0]["url"] = "http://example.com/base"

    errors = validate_scenario_analysis(analysis, today=date(2026, 10, 19))
    assert any("sumar exactamente 100%" in error for error in errors)
    assert any("debe ser HTTPS" in error for error in errors)
    assert calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="USD")["validation_status"] == "invalid"


def test_expired_horizon_and_placeholder_source_identifier_are_invalid():
    analysis = scenario_set()
    analysis["horizon_date"] = "2026-10-18"
    analysis["as_of_date"] = "2026-10-18"
    analysis["scenarios"][0]["sources"][0]["url"] = (
        "https://www.sec.gov/Archives/edgar/data/0000000000/0000000000-23-000001.xbrl"
    )

    errors = validate_scenario_analysis(analysis, today=date(2026, 10, 19))

    assert any("posterior a la fecha actual" in error for error in errors)
    assert any("coincidir con la fecha actual" in error for error in errors)
    assert any("identificador de relleno" in error for error in errors)


def test_currency_mismatch_and_unsupported_one_sided_distribution_block_calculation():
    analysis = scenario_set()
    assert "moneda" in calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="ARS")["validation_reason"]

    for scenario in analysis["scenarios"]:
        scenario["target_price"] = 110
    result = calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="USD")
    assert result["validation_status"] == "invalid"
    assert "upside y downside" in result["validation_reason"]


def test_scenario_review_is_bound_to_exact_content_and_requires_rationale():
    analysis = scenario_set()
    review = {
        "status": "approved",
        "scenario_hash": scenario_fingerprint(analysis),
        "reviewed_by": "manager",
        "reviewed_at": "2026-10-19T12:00:00-03:00",
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    assert validate_scenario_review(analysis, review, today=date(2026, 10, 19)) == (True, "escenarios vigentes aprobados por el gestor")

    analysis["scenarios"][2]["target_price"] = 155
    approved, reason = validate_scenario_review(analysis, review, today=date(2026, 10, 19))
    assert not approved
    assert "no corresponde" in reason


def test_rule_008_requires_manager_review_for_explicit_scenario_contract():
    analysis = scenario_set()
    report = {"scenario_analysis": analysis}
    pending = _calculate_report_asymmetry(report, [], 100, None, None, None, "USD", None)
    assert pending["validation_status"] == "validated"
    assert pending["authorization_eligible"] is False
    assert not _eval_asymmetry({"asymmetry": pending}).passed

    review = {
        "status": "approved",
        "scenario_hash": scenario_fingerprint(analysis),
        "reviewed_by": "manager",
        "reviewed_at": "2026-10-19T12:00:00-03:00",
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    approved = _calculate_report_asymmetry(report, [], 100, None, None, None, "USD", review)
    assert approved["authorization_eligible"] is True
    assert _eval_asymmetry({"asymmetry": approved}).passed == (approved["benefit_risk_ratio"] >= 3)


def test_rejected_or_unattributed_review_cannot_authorize():
    analysis = scenario_set()
    review = {
        "status": "approved",
        "scenario_hash": scenario_fingerprint(analysis),
        "reviewed_by": "",
        "reviewed_at": "2026-10-19T12:00:00-03:00",
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    approved, reason = validate_scenario_review(analysis, review, today=date(2026, 10, 19))
    assert not approved
    assert "identidad" in reason
    review["reviewed_by"] = "manager"
    review["sources_verified"] = False
    approved, reason = validate_scenario_review(analysis, review, today=date(2026, 10, 19))
    assert not approved
    assert "no confirmó" in reason
    review["status"] = "rejected"
    review["reviewed_by"] = "manager"
    approved, _ = validate_scenario_review(analysis, review, today=date(2026, 10, 19))
    assert not approved


def test_review_command_records_authenticated_identity_for_current_hash(tmp_path):
    analysis = scenario_set()
    opp_dir = tmp_path / "idos-journal/companies/ACME/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump({"scenario_analysis": analysis}), encoding="utf-8")

    path = record_scenario_review(
        tmp_path, "ACME", "OPP-1", scenario_fingerprint(analysis), "approved",
        "github-manager", "Checked source links, source dates and target assumptions.", True,
    )
    review = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert review["status"] == "approved"
    assert review["reviewed_by"] == "github-manager"
    assert review["scenario_hash"] == scenario_fingerprint(analysis)
    assert review["sources_verified"] is True
    with pytest.raises(ValueError, match="source and source-date verification"):
        record_scenario_review(
            tmp_path, "ACME", "OPP-1", scenario_fingerprint(analysis), "approved",
            "github-manager", "Approved without verifying sources.",
        )


def test_review_command_rejects_stale_hash_and_path_traversal(tmp_path):
    analysis = scenario_set()
    opp_dir = tmp_path / "idos-journal/companies/ACME/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump({"scenario_analysis": analysis}), encoding="utf-8")

    args = (tmp_path, "ACME", "OPP-1")
    with pytest.raises(ValueError, match="stale"):
        record_scenario_review(*args, "0" * 64, "approved", "github-manager", "Checked scenario sources.", True)
    with pytest.raises(ValueError, match="Opportunity id"):
        record_scenario_review(tmp_path, "ACME", "../private", scenario_fingerprint(analysis), "approved", "github-manager", "Checked scenario sources.", True)
