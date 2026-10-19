from idos.decision.assessment_pipeline import (
    _authorization_rule_ids,
    _eval_financial_data_quality,
    _financial_data_quality,
    _register_authorization_rules,
)
from idos.decision.orchestrator import DecisionOrchestrator
from idos.rules.engine import RulesEngine


def test_financial_data_quality_accepts_zero_as_a_valid_numeric_value():
    quality = _financial_data_quality({
        "roic_pct": 0,
        "operating_margin_pct": 0,
        "revenue_growth_pct": 0,
        "pe_ratio_ttm": 0,
        "debt_equity_ratio": 0,
        "source": "provider-x",
        "fundamentals_as_of": "2026-09-30",
    })

    assert quality["status"] == "good"
    assert quality["core_metric_coverage"] == "5/5"
    assert quality["missing_core_metrics"] == []


def test_financial_data_quality_exposes_missing_as_of_date():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })

    assert quality["status"] == "partial"
    assert quality["missing_provenance"] == ["as_of_date"]


def test_financial_data_quality_marks_sparse_core_metrics_poor():
    quality = _financial_data_quality({"source": "provider-x", "as_of_date": "2026-09-30"})

    assert quality["status"] == "poor"
    assert quality["core_metric_coverage"] == "0/5"
    assert set(quality["missing_core_metrics"]) == {
        "roic", "operating_margin", "revenue_growth", "pe_ratio", "debt_to_equity"
    }


def test_financial_quality_gate_blocks_missing_cutoff_and_passes_valid_partial_coverage():
    missing_cutoff = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })
    blocked = _eval_financial_data_quality({"financial_data_quality": missing_cutoff})
    assert not blocked.passed
    assert "fecha de corte ausente" in blocked.details

    partial_with_provenance = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "source": "provider-x",
        "fundamentals_as_of": "2026-09-30",
    })
    passed = _eval_financial_data_quality({"financial_data_quality": partial_with_provenance})
    assert partial_with_provenance["status"] == "partial"
    assert partial_with_provenance["core_metric_coverage"] == "4/5"
    assert passed.passed


def test_financial_quality_gate_rejects_malformed_or_future_cutoff():
    for cutoff in ("2026-02-30", "2027-01-01", "not-a-date"):
        quality = _financial_data_quality({
            "roic_pct": 25,
            "operating_margin_pct": 20,
            "revenue_growth_pct": 5,
            "pe_ratio_ttm": 18,
            "debt_equity_ratio": 0.5,
            "source": "provider-x",
            "as_of_date": cutoff,
        })
        result = _eval_financial_data_quality({"financial_data_quality": quality})
        assert quality["as_of_date"] is None
        assert not result.passed


def test_financial_quality_uses_provider_reported_unix_cutoff_and_its_source():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "source": "stockanalysis.com",
        "financial_period_end_timestamp": 1782518400,
        "data_provenance": {
            "field_sources": {"financial_period_end_timestamp": ["yfinance"]},
        },
    })

    assert quality["as_of_date"] == "2026-06-27"
    assert quality["as_of_date_source"] == "yfinance"
    assert quality["status"] == "partial"
    assert _eval_financial_data_quality({"financial_data_quality": quality}).passed

    for timestamp in (1782518400000, 1800000000):
        invalid = _financial_data_quality({
            "roic_pct": 25,
            "operating_margin_pct": 20,
            "revenue_growth_pct": 5,
            "pe_ratio_ttm": 18,
            "debt_equity_ratio": 0.5,
            "source": "provider-x",
            "financial_period_end_timestamp": timestamp,
            "data_provenance": {
                "field_sources": {"financial_period_end_timestamp": ["yfinance"]},
            },
        })
        assert invalid["as_of_date"] is None
        assert not _eval_financial_data_quality({"financial_data_quality": invalid}).passed


def test_financial_quality_rule_cannot_be_disabled_by_custom_authorization_config(tmp_path):
    rules_path = tmp_path / "idos-config" / "rules" / "entry_rules.yml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        "rules:\n  - id: RULE-005\n    active: true\n    stage: authorization\n",
        encoding="utf-8",
    )

    assert "RULE-010" in _authorization_rule_ids(tmp_path)


def test_missing_cutoff_blocks_orchestrated_decision_even_with_high_conviction(tmp_path):
    rules_path = tmp_path / "idos-config" / "rules" / "entry_rules.yml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        "rules:\n  - id: RULE-005\n    active: true\n    stage: authorization\n",
        encoding="utf-8",
    )
    engine = RulesEngine()
    _register_authorization_rules(engine, tmp_path)
    orchestrator = DecisionOrchestrator(rules_engine=engine)
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })

    proposal = orchestrator.run_pipeline("opportunity:transitioned", {
        "opportunity_id": "OPP-QUALITY-001",
        "ticker": "AAPL",
        "force_relevance": True,
        "financial_data_quality": quality,
        "precomputed_assessments": {
            "BusinessAssessmentEngine": 90,
            "ValuationAssessmentEngine": 90,
            "RecoveryAssessmentEngine": 90,
            "RiskAssessmentEngine": 90,
            "PortfolioAssessmentEngine": 90,
        },
    })

    assert proposal is not None
    assert proposal.conviction_score >= 70
    assert proposal.recommendation == "BLOCKED"
    assert "RULE-010" in proposal.rules_failed
