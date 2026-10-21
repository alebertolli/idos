from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from idos.decision.scenarios import (
    calculate_scenario_asymmetry,
    scenario_fingerprint,
    scenario_source_urls_from_evidence,
    scenario_source_urls_from_research_financial_evidence,
    scenario_financial_evidence_snapshot,
    scenario_source_urls_from_report,
    validate_scenario_analysis,
    validate_board_scenario_confirmation,
)
from idos.decision.assessment_pipeline import _calculate_report_asymmetry, _eval_asymmetry


AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
TODAY = datetime.now(AR_TZ).date()
SOURCE_DATE = (TODAY - timedelta(days=1)).isoformat()
REVIEWED_AT = datetime.combine(TODAY, datetime.min.time(), tzinfo=AR_TZ).replace(hour=12).isoformat()


def scenario_set():
    return {
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


def test_valid_bear_base_bull_contract_and_expected_asymmetry():
    analysis = scenario_set()

    assert validate_scenario_analysis(analysis, today=TODAY) == []
    asymmetry = calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="USD")
    assert asymmetry["validation_status"] == "validated"
    assert asymmetry["board_review_eligible"] is True
    assert asymmetry["upside_esperado_pct"] == 17.5
    assert asymmetry["downside_esperado_pct"] == -5
    assert asymmetry["benefit_risk_ratio"] == 3.5


def test_invalid_scenario_contract_fails_closed():
    analysis = scenario_set()
    analysis["scenarios"][0]["probability_pct"] = 30
    analysis["scenarios"][1]["sources"][0]["url"] = "http://example.com/base"

    errors = validate_scenario_analysis(analysis, today=TODAY)
    assert any("sumar exactamente 100%" in error for error in errors)
    assert any("debe ser HTTPS" in error for error in errors)
    assert calculate_scenario_asymmetry(analysis, current_price=100, quote_currency="USD")["validation_status"] == "invalid"


def test_scenario_sources_must_be_present_in_structured_market_evidence():
    analysis = scenario_set()
    evidence = {
        "current_quote": {"sources": [{"url": "https://example.com/bear"}]},
        "analyst_target_consensus": {"sources": [{"url": "https://example.com/base"}]},
    }
    trusted = scenario_source_urls_from_evidence(json.dumps(evidence))

    errors = validate_scenario_analysis(analysis, today=TODAY, trusted_source_urls=trusted)

    assert any("BULL.sources[0]" in error and "no está respaldada" in error for error in errors)
    assert not any("BEAR.sources[0]" in error for error in errors)
    assert not any("BASE.sources[0]" in error for error in errors)



def test_scenario_sources_accept_exact_research_financial_urls_and_ignore_invalid_urls():
    evidence = {
        "source_observations": {
            "revenue_history": {"source_url": "https://stockanalysis.com/stocks/asml/financials/"},
            "bad": {"source_url": "http://example.com/data"},
        },
        "validated_metric_observations": {
            "fcf_history": [
                {"source_url": "https://finance.yahoo.com/quote/ASML/cash-flow/"},
                {"source_url": "javascript:alert(1)"},
            ],
        },
        "unscoped_url_list": ["https://not-admitted.example/data"],
    }

    trusted = scenario_source_urls_from_research_financial_evidence(evidence)

    assert trusted == {
        "https://stockanalysis.com/stocks/asml/financials",
        "https://finance.yahoo.com/quote/ASML/cash-flow",
    }


def test_report_scenario_source_allowlist_combines_market_and_financial_evidence():
    report = {
        "research_input_snapshot": {
            "scenario_market_evidence": {
                "current_quote": {"sources": [{"url": "https://finance.yahoo.com/quote/ASML/"}]},
            },
            "scenario_financial_evidence": {
                "source_observations": {
                    "revenue_history": {"source_url": "https://stockanalysis.com/stocks/asml/financials/"},
                },
            },
        },
    }

    assert scenario_source_urls_from_report(report) == {
        "https://finance.yahoo.com/quote/ASML",
        "https://stockanalysis.com/stocks/asml/financials",
    }


def test_scenario_financial_snapshot_keeps_source_metadata_without_values():
    snapshot = scenario_financial_evidence_snapshot({
        "source_observations": {
            "revenue_history": {
                "value": [100, 120],
                "source_url": "https://stockanalysis.com/stocks/asml/financials/",
                "unit": "USD",
                "currency": "USD",
                "period_type": "annual",
                "period_end": "2025-12-31",
                "sources": ["stockanalysis"],
            },
        },
    })

    assert snapshot["source_observations"]["revenue_history"] == {
        "source_url": "https://stockanalysis.com/stocks/asml/financials",
        "unit": "USD",
        "currency": "USD",
        "period_type": "annual",
        "period_end": "2025-12-31",
        "sources": ["stockanalysis"],
    }
    assert "value" not in snapshot["source_observations"]["revenue_history"]


def test_ticker_case_only_scenario_urls_canonicalize_to_supplied_evidence():
    from idos.decision.scenarios import canonicalize_scenario_ticker_url_case

    analysis = scenario_set()
    trusted_url = "https://stockanalysis.com/stocks/alab/forecast"
    for scenario in analysis["scenarios"]:
        scenario["sources"][0]["url"] = "https://stockanalysis.com/stocks/ALAB/forecast/"
    trusted = scenario_source_urls_from_evidence(json.dumps({
        "analyst_target_consensus": {"sources": [{"url": trusted_url}]},
    }))

    corrected = canonicalize_scenario_ticker_url_case(
        analysis, ticker="ALAB", trusted_source_urls=trusted
    )

    assert all(s["sources"][0]["url"] == trusted_url for s in corrected["scenarios"])
    assert validate_scenario_analysis(corrected, today=TODAY, trusted_source_urls=trusted) == []
    assert all(s["sources"][0]["url"].endswith("/ALAB/forecast/") for s in analysis["scenarios"])


def test_scenario_url_canonicalization_rejects_unrelated_path_changes():
    from idos.decision.scenarios import canonicalize_scenario_ticker_url_case

    analysis = scenario_set()
    analysis["scenarios"][0]["sources"][0]["url"] = "https://stockanalysis.com/stocks/ALAB/history/"
    trusted = {"https://stockanalysis.com/stocks/alab/forecast"}

    corrected = canonicalize_scenario_ticker_url_case(
        analysis, ticker="ALAB", trusted_source_urls=trusted
    )

    assert corrected["scenarios"][0]["sources"][0]["url"].endswith("/ALAB/history/")

def test_report_source_evidence_is_used_to_block_unverified_asymmetry():
    analysis = scenario_set()
    report = {
        "scenario_analysis": analysis,
        "research_input_snapshot": {
            "scenario_market_evidence": {
                "current_quote": {"sources": [{"url": "https://example.com/bear"}]},
                "analyst_target_consensus": {"sources": [{"url": "https://example.com/base"}]},
            },
        },
    }

    trusted = scenario_source_urls_from_report(report)
    asymmetry = _calculate_report_asymmetry(report, [], 100, None, None, None, "USD")

    assert trusted == {"https://example.com/bear", "https://example.com/base"}
    assert asymmetry["validation_status"] == "invalid"
    assert "no está respaldada" in asymmetry["validation_reason"]
    assert asymmetry["board_review_eligible"] is False


def test_expired_horizon_and_placeholder_source_identifier_are_invalid():
    analysis = scenario_set()
    analysis["horizon_date"] = SOURCE_DATE
    analysis["as_of_date"] = SOURCE_DATE
    analysis["scenarios"][0]["sources"][0]["url"] = (
        "https://www.sec.gov/Archives/edgar/data/0000000000/0000000000-23-000001.xbrl"
    )

    errors = validate_scenario_analysis(analysis, today=TODAY)

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


def test_decision_board_scenario_confirmation_is_bound_to_exact_content():
    analysis = scenario_set()
    review = {
        "status": "approved",
        "scenario_hash": scenario_fingerprint(analysis),
        "reviewed_by": "manager",
        "reviewed_at": REVIEWED_AT,
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    assert validate_board_scenario_confirmation(analysis, review, today=TODAY) == (True, "escenarios y fuentes confirmados en Decision Board")

    analysis["scenarios"][2]["target_price"] = 155
    approved, reason = validate_board_scenario_confirmation(analysis, review, today=TODAY)
    assert not approved
    assert "no corresponde" in reason


def test_rule_008_automatically_validates_scenarios_for_decision_board():
    analysis = scenario_set()
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
    ready = _calculate_report_asymmetry(report, [], 100, None, None, None, "USD")
    assert ready["validation_status"] == "validated"
    assert ready["board_review_eligible"] is True
    assert ready["scenario_hash"] == scenario_fingerprint(analysis)
    assert _eval_asymmetry({"asymmetry": ready}).passed == (ready["benefit_risk_ratio"] >= 3)


def test_rejected_or_unattributed_review_cannot_authorize():
    analysis = scenario_set()
    review = {
        "status": "approved",
        "scenario_hash": scenario_fingerprint(analysis),
        "reviewed_by": "",
        "reviewed_at": REVIEWED_AT,
        "note": "Reviewed source links, dates and valuation assumptions.",
        "sources_verified": True,
    }
    approved, reason = validate_board_scenario_confirmation(analysis, review, today=TODAY)
    assert not approved
    assert "identidad autenticada" in reason
    review["reviewed_by"] = "manager"
    review["sources_verified"] = False
    approved, reason = validate_board_scenario_confirmation(analysis, review, today=TODAY)
    assert not approved
    assert "no confirmó" in reason
    review["status"] = "rejected"
    review["reviewed_by"] = "manager"
    approved, _ = validate_board_scenario_confirmation(analysis, review, today=TODAY)
    assert not approved


