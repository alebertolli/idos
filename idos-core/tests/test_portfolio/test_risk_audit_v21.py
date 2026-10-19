from copy import deepcopy

from idos.portfolio.audit import audit_portfolio


def evidence(value, unit, source_ref="statement-1"):
    return {"value": value, "unit": unit, "as_of": "2026-10-15", "source_ref": source_ref}


def snapshot_with_bond():
    return {
        "as_of": "2026-10-15",
        "base_currency": "USD",
        "positions": [{
            "position_id": "bond-1", "source_ref": "custody-statement-1",
            "currency": "USD", "market_value": 1000, "issuer": "Issuer A",
            "economic_cluster": "Issuer A", "strategy_id": "CREDIT",
            "risk_profile": {
                "schema_version": "1.0",
                "instrument_type": "CORPORATE_DEBT",
                "distressed_assessment": {
                    "value": False, "as_of": "2026-10-15", "source_ref": "credit-review-1"
                },
                "credit_classification": {
                    "issuer_type": "CORPORATE",
                    "seniority": "SENIOR_UNSECURED",
                    "rating": "BBB",
                    "as_of": "2026-10-15",
                    "source_ref": "rating-report-1",
                },
                "metrics": {
                    "modified_duration_years": evidence(4, "years"),
                    "convexity": evidence(20, "years_squared"),
                    "annualized_volatility_pct": evidence(8, "percent"),
                    "spread_duration_years": evidence(3, "years"),
                    "pd_1y_pct": evidence(2, "percent"),
                    "lgd_pct": evidence(40, "percent"),
                    "risk_intensity": evidence(0.2, "ratio"),
                    "correlation_adjustment": evidence(1.1, "ratio"),
                },
                "return_stream_id": "issuer-a-credit",
                "economic_currency_exposures": [{
                    "currency": "USD", "exposure_pct": evidence(100, "percent")
                }],
            },
        }],
        "correlations": [],
        "risk_budget": {
            "capacity_base": evidence(1000, "base_currency", "policy-1"),
            "used_base": evidence(300, "base_currency", "policy-1"),
        },
    }


def test_risk_audit_uses_explicit_duration_convexity_and_credit_inputs():
    report = audit_portfolio(snapshot_with_bond())

    assert report["risk_audit_status"] == "PARTIAL"
    assert report["allocation_authorized"] is False
    assert report["risk_audit_methodology"] == "risk_audit_v2_1_evidence_driven_v1"
    assert report["credit_expected_loss_base"] == 8
    scenarios = {row["scenario_id"]: row for row in report["scenarios"]}
    assert scenarios["INTEREST_RATE_UP_100"]["positions"][0]["pnl_base"] == -39
    assert scenarios["CREDIT_SPREAD_UP_100"]["positions"][0]["pnl_base"] == -30
    assert scenarios["GLOBAL_EQUITY_CRASH_-20"]["status"] == "PARTIAL"
    assert report["risk_budget"]["available_base"] == 700
    assert "liquidity_under_normal_and_stress" in report["risk_dimensions_not_assessed"]


def test_distressed_credit_exposes_sourced_recovery_waterfall_and_scenarios():
    snapshot = snapshot_with_bond()
    profile = snapshot["positions"][0]["risk_profile"]
    profile["distressed_assessment"] = {
        "value": True, "as_of": "2026-10-15", "source_ref": "credit-review-2"
    }
    profile["recovery_analysis"] = {
        "enterprise_value_base": evidence(1500, "base_currency", "recovery-model"),
        "senior_debt_base": evidence(500, "base_currency", "recovery-model"),
        "secured_debt_base": evidence(300, "base_currency", "recovery-model"),
        "unsecured_debt_base": evidence(200, "base_currency", "recovery-model"),
        "priority_obligations_base": evidence(100, "base_currency", "recovery-model"),
        "assets_available_base": evidence(1200, "base_currency", "recovery-model"),
        "recovery_min_pct": evidence(35, "percent", "recovery-model"),
        "recovery_base_pct": evidence(55, "percent", "recovery-model"),
        "recovery_optimistic_pct": evidence(75, "percent", "recovery-model"),
    }

    report = audit_portfolio(snapshot)

    credit = report["risk_positions"][0]["credit_risk"]
    assert credit["status"] == "ASSESSED"
    assert credit["recovery_analysis_status"] == "ASSESSED"
    assert credit["recovery_analysis"]["waterfall_base"]["enterprise_value_base"] == 1500
    assert credit["recovery_analysis"]["recovery_scenarios_pct"] == {
        "minimum": 35, "base": 55, "optimistic": 75
    }


def test_scenario_requires_dated_sourced_metrics_and_does_not_assume_zero():
    snapshot = snapshot_with_bond()
    del snapshot["positions"][0]["risk_profile"]["metrics"]["modified_duration_years"]
    report = audit_portfolio(snapshot)

    scenario = next(row for row in report["scenarios"] if row["scenario_id"] == "INTEREST_RATE_UP_100")
    assert scenario["status"] == "PARTIAL"
    assert scenario["total_pnl_base"] is None
    assert scenario["positions"][0]["status"] == "UNKNOWN"
    assert report["risk_positions"][0]["market_risk"]["status"] == "UNKNOWN"


def test_rate_stress_remains_unknown_when_convexity_is_missing():
    snapshot = snapshot_with_bond()
    del snapshot["positions"][0]["risk_profile"]["metrics"]["convexity"]

    report = audit_portfolio(snapshot)

    scenario = next(row for row in report["scenarios"] if row["scenario_id"] == "INTEREST_RATE_UP_100")
    assert scenario["status"] == "PARTIAL"
    assert scenario["total_pnl_base"] is None
    assert scenario["positions"][0]["status"] == "UNKNOWN"


def test_sizing_uses_minimum_of_five_explicit_limits_only():
    snapshot = snapshot_with_bond()
    profile = snapshot["positions"][0]["risk_profile"]
    profile["allocation_limits"] = {
        "risk_capacity_limit_pct": evidence(3, "percent", "risk-policy"),
        "opportunity_limit_pct": evidence(2, "percent", "opportunity-policy"),
        "portfolio_limit_pct": evidence(4, "percent", "portfolio-policy"),
        "liquidity_limit_pct": evidence(1.5, "percent", "liquidity-policy"),
        "architecture_limit_pct": evidence(5, "percent", "architecture-policy"),
    }

    report = audit_portfolio(snapshot)

    sizing = report["position_sizing"][0]
    assert sizing["status"] == "ASSESSED"
    assert sizing["final_weight_limit_pct"] == 1.5
    assert report["allocation_authorized"] is False


def test_risk_evidence_after_snapshot_is_unknown():
    snapshot = snapshot_with_bond()
    snapshot["positions"][0]["risk_profile"]["metrics"]["modified_duration_years"]["as_of"] = "2026-10-16"

    report = audit_portfolio(snapshot)

    scenario = next(row for row in report["scenarios"] if row["scenario_id"] == "INTEREST_RATE_UP_100")
    assert scenario["positions"][0]["status"] == "UNKNOWN"
    assert report["risk_audit_status"] == "PARTIAL"


def test_unsupported_risk_profile_schema_is_not_interpreted():
    snapshot = snapshot_with_bond()
    snapshot["positions"][0]["risk_profile"]["schema_version"] = "2.0"

    report = audit_portfolio(snapshot)

    position = report["risk_positions"][0]
    assert position["risk_profile_schema_status"] == "UNKNOWN"
    assert position["instrument_type"] == "UNKNOWN"
    assert report["risk_audit_status"] == "PARTIAL"
    assert report["risk_contributions"]["status"] == "UNKNOWN"


def _add_position_on_stream(snapshot, position_id, stream_id):
    position = deepcopy(snapshot["positions"][0])
    position["position_id"] = position_id
    position["issuer"] = f"Issuer {position_id}"
    position["economic_cluster"] = f"Cluster {position_id}"
    position["risk_profile"]["return_stream_id"] = stream_id
    snapshot["positions"].append(position)


def test_correlation_coverage_requires_each_unique_return_stream_pair():
    snapshot = snapshot_with_bond()
    _add_position_on_stream(snapshot, "bond-2", "stream-b")
    _add_position_on_stream(snapshot, "bond-3", "stream-c")
    snapshot["positions"][0]["risk_profile"]["return_stream_id"] = "stream-a"
    snapshot["correlations"] = [
        {"position_id_a": "bond-1", "position_id_b": "bond-2", "value": 0.2, "as_of": "2026-10-15", "source_ref": "corr-ab"},
        {"position_id_a": "bond-1", "position_id_b": "bond-3", "value": 0.1, "as_of": "2026-10-15", "source_ref": "corr-ac"},
        {"position_id_a": "bond-2", "position_id_b": "bond-3", "value": 0.3, "as_of": "2026-10-15", "source_ref": "corr-bc"},
    ]

    report = audit_portfolio(snapshot)
    correlation = report["correlation_and_return_streams"]

    assert correlation["status"] == "ASSESSED"
    assert correlation["return_stream_count"] == 3
    assert correlation["expected_pair_count"] == 3
    assert correlation["observed_pair_count"] == 3
    assert correlation["missing_pairs"] == []


def test_duplicate_correlation_rows_cannot_hide_missing_stream_pairs():
    snapshot = snapshot_with_bond()
    _add_position_on_stream(snapshot, "bond-2", "stream-b")
    _add_position_on_stream(snapshot, "bond-3", "stream-c")
    snapshot["positions"][0]["risk_profile"]["return_stream_id"] = "stream-a"
    snapshot["correlations"] = [
        {"position_id_a": "bond-1", "position_id_b": "bond-2", "value": 0.2, "as_of": "2026-10-15", "source_ref": "corr-ab-1"},
        {"position_id_a": "bond-2", "position_id_b": "bond-1", "value": 0.25, "as_of": "2026-10-15", "source_ref": "corr-ab-2"},
        {"position_id_a": "bond-1", "position_id_b": "bond-3", "value": 0.1, "as_of": "2026-10-15", "source_ref": "corr-ac"},
    ]

    correlation = audit_portfolio(snapshot)["correlation_and_return_streams"]

    assert correlation["status"] == "PARTIAL"
    assert correlation["expected_pair_count"] == 3
    assert correlation["observed_pair_count"] == 2
    assert correlation["duplicate_pairs"] == [["stream-a", "stream-b"]]
    assert correlation["missing_pairs"] == [["stream-b", "stream-c"]]


def test_positions_in_one_return_stream_do_not_require_pairwise_correlations():
    snapshot = snapshot_with_bond()
    _add_position_on_stream(snapshot, "bond-2", "issuer-a-credit")
    snapshot["correlations"] = []

    correlation = audit_portfolio(snapshot)["correlation_and_return_streams"]

    assert correlation["status"] == "ASSESSED"
    assert correlation["return_stream_count"] == 1
    assert correlation["return_streams"] == [{
        "return_stream_id": "issuer-a-credit",
        "position_ids": ["bond-1", "bond-2"],
    }]


def test_missing_return_stream_identity_keeps_correlation_partial():
    snapshot = snapshot_with_bond()
    _add_position_on_stream(snapshot, "bond-2", "stream-b")
    snapshot["positions"][0]["risk_profile"].pop("return_stream_id")
    snapshot["correlations"] = [
        {"return_stream_id_a": "issuer-a-credit", "return_stream_id_b": "stream-b", "value": 0.2, "as_of": "2026-10-15", "source_ref": "corr-ab"},
    ]

    correlation = audit_portfolio(snapshot)["correlation_and_return_streams"]

    assert correlation["status"] == "PARTIAL"
    assert correlation["positions_without_return_stream"] == ["bond-1"]
