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


def test_portfolio_engine():
    engine = PortfolioAssessmentEngine()
    ctx = {
        "company": {"sector": "Technology"},
        "portfolio": {
            "total_weight": 60.0,
            "sector_exposure": {"Technology": 20.0},
            "num_positions": 12,
            "thematic_correlations": {},
        },
        "proposed_weight": 3.0,
        "themes": ["AI", "Cloud"],
    }
    result = engine.evaluate(ctx)
    assert 0 <= result.score <= 100
