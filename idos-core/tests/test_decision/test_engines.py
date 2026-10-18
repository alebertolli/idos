import pytest

from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine


def test_business_engine_high_score():
    engine = BusinessAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "static": {"moat_description": "Strong brand and network effects"},
            "dynamic": {
                "metrics": {
                    "roic": 28,
                    "revenue_growth": 25,
                    "operating_margin": 30,
                }
            },
        }
    }
    result = engine.evaluate(ctx)
    assert result.score >= 80
    assert result.engine == "BusinessAssessmentEngine"


def test_business_engine_low_score():
    engine = BusinessAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {"metrics": {"roic": 3, "revenue_growth": 2, "operating_margin": 2}}
        }
    }
    result = engine.evaluate(ctx)
    assert result.score <= 40


def test_valuation_engine_attractive():
    engine = ValuationAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "pe_ratio": 12,
                    "pe_historical_avg": 20,
                    "fcf_yield": 6.5,
                }
            }
        },
        "margin_of_safety": 45,
    }
    result = engine.evaluate(ctx)
    assert result.score >= 70
    assert result.recommendation == "ATTRACTIVE"


def test_recovery_engine():
    engine = RecoveryAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "revenue_growth": 20,
                    "eps_growth": 18,
                    "fcf_growth": 15,
                    "roic": 22,
                    "pe_ratio": 12,
                    "pe_historical_avg": 20,
                    "fcf_yield": 5,
                    "short_interest_pct": 12,
                }
            }
        },
        "margin_of_safety": 40,
        "catalysts": [
            {"impact": "high", "timeline": "short"},
            {"impact": "medium", "timeline": "medium"},
        ],
    }
    result = engine.evaluate(ctx)
    assert 0 <= result.score <= 100
    assert len(result.findings) == 6


def test_recovery_engine_accepts_missing_valuation_evidence():
    result = RecoveryAssessmentEngine().evaluate({"margin_of_safety": None})

    assert result.recommendation != "ERROR"
    assert 0 <= result.score <= 100


def test_risk_engine():
    engine = RiskAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "debt_to_equity": 0.2,
                    "volatility_90d": 25,
                    "current_ratio": 2.5,
                }
            }
        },
        "portfolio": {"position_weight": 2.0},
    }
    result = engine.evaluate(ctx)
    assert result.score >= 70


def test_risk_engine_high_leverage():
    engine = RiskAssessmentEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "debt_to_equity": 3.5,
                    "volatility_90d": 45,
                    "current_ratio": 0.7,
                }
            }
        },
        "portfolio": {"position_weight": 4.0},
    }
    result = engine.evaluate(ctx)
    assert result.score <= 40
    assert len(result.risks) >= 2


def test_risk_engine_does_not_treat_missing_metrics_as_low_risk():
    result = RiskAssessmentEngine().evaluate({})

    assert result.score == 0
    assert result.confidence == "LOW"
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert not any(finding.get("detail") == "Low leverage" for finding in result.findings)
    assert {risk["metric"] for risk in result.risks if risk["type"] == "DATA_QUALITY"} == {
        "debt_to_equity", "volatility_90d", "current_ratio"
    }


def test_risk_engine_preserves_missingness_before_legacy_zero_normalization():
    from idos.decision.assessment_pipeline import _attach_risk_metric_availability, _normalize_decimal_pcts

    financial = _attach_risk_metric_availability({"current_ratio": 1.4})
    financial = _normalize_decimal_pcts(financial)
    context = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "debt_to_equity": financial.get("debt_equity_ratio", 0),
                    "volatility_90d": financial.get("volatility_90d", 0),
                    "current_ratio": financial.get("current_ratio", 0),
                },
                "metric_availability": financial["_risk_metric_availability"],
            }
        }
    }

    result = RiskAssessmentEngine().evaluate(context)

    assert context["knowledge_base"]["dynamic"]["metrics"]["debt_to_equity"] == 0
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert result.score == 0
    assert not any(finding.get("detail") == "Low leverage" for finding in result.findings)


def test_risk_metric_availability_fills_unreported_metadata_conservatively():
    from idos.decision.assessment_pipeline import _attach_risk_metric_availability

    financial = _attach_risk_metric_availability({
        "debt_equity_ratio": 0.2,
        "current_ratio": 1.2,
        "_risk_metric_availability": {"current_ratio": True},
    })

    assert financial["_risk_metric_availability"] == {
        "debt_to_equity": True,
        "volatility_90d": False,
        "current_ratio": True,
    }


@pytest.mark.parametrize("metric_name, invalid_value", [
    ("debt_to_equity", -0.1),
    ("volatility_90d", float("inf")),
    ("current_ratio", float("nan")),
])
def test_risk_engine_blocks_invalid_numeric_inputs(metric_name, invalid_value):
    metrics = {"debt_to_equity": 1.2, "volatility_90d": 20, "current_ratio": 1.5}
    metrics[metric_name] = invalid_value

    result = RiskAssessmentEngine().evaluate({"knowledge_base": {"dynamic": {"metrics": metrics}}})

    assert result.score == 0
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert any(risk.get("metric") == metric_name and risk["type"] == "DATA_QUALITY" for risk in result.risks)


def test_portfolio_engine():
    engine = PortfolioAssessmentEngine()
    ctx = {
        "company": {"sector": "Technology"},
        "portfolio": {
            "total_weight": 60.0,
            "sector_exposure": {"Technology": 20.0},
            "num_positions": 12,
            "thematic_correlations": {},
            "source": "private_snapshot",
            "snapshot_id": "snapshot-2026-10-16",
            "as_of": "2026-10-16",
            "reconciled": True,
        },
        "proposed_weight": 3.0,
        "themes": ["AI", "Cloud"],
    }
    result = engine.evaluate(ctx)
    assert 0 <= result.score <= 100


@pytest.mark.parametrize("portfolio", [
    {},
    {"source": "paper_simulation", "snapshot_id": "paper-1", "as_of": "2026-10-16", "reconciled": True},
    {"source": "private_snapshot", "snapshot_id": "snapshot-1", "as_of": "2026-10-16", "reconciled": False},
    {"source": "private_snapshot", "snapshot_id": "", "as_of": "2026-10-16", "reconciled": True},
])
def test_portfolio_engine_fails_closed_without_reconciled_private_snapshot(portfolio):
    result = PortfolioAssessmentEngine().evaluate({"portfolio": portfolio})

    assert result.score == 0
    assert result.confidence == "LOW"
    assert result.recommendation == "INSUFFICIENT_PORTFOLIO_DATA"
    assert result.findings == []
    assert result.risks[0]["type"] == "DATA_QUALITY"
