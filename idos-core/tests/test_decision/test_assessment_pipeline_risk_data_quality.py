import sys
from types import SimpleNamespace

from idos.decision import assessment_pipeline
from idos.data.journal import JournalRepository
from idos.decision.engines.valuation import ValuationAssessmentEngine


def test_build_context_preserves_financial_risk_metric_availability(tmp_path, monkeypatch):
    availability = {
        "debt_to_equity": False,
        "volatility_90d": True,
        "current_ratio": True,
    }
    monkeypatch.setattr(
        assessment_pipeline,
        "_load_financial_data",
        lambda *_: {
            "debt_equity_ratio": 0,
            "volatility_90d": 22,
            "current_ratio": 1.3,
            "_risk_metric_availability": availability,
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _ticker: SimpleNamespace(info={})),
    )

    class Knowledge:
        @staticmethod
        def load_company(_ticker):
            return {}

    class SQLite:
        @staticmethod
        def get_opportunity(_opp_id):
            return None

    context = assessment_pipeline.build_context(
        "OPP-1", "TEST", tmp_path, SQLite(), Knowledge(), JournalRepository(tmp_path / "idos-journal")
    )

    dynamic = context["knowledge_base"]["dynamic"]
    assert dynamic["metrics"]["debt_to_equity"] == 0
    assert dynamic["metric_availability"] == availability
    assert context["portfolio"]["source"] == "unavailable"
    assert context["portfolio"]["reconciled"] is False


def test_cache_only_context_does_not_invent_price_margin_or_mos(tmp_path, monkeypatch):
    monkeypatch.setattr(
        assessment_pipeline,
        "_load_financial_data",
        lambda *_args, **_kwargs: {"price": None, "price_target_avg": None},
    )

    class Knowledge:
        @staticmethod
        def load_company(_ticker):
            return {}

    class SQLite:
        @staticmethod
        def get_opportunity(_opp_id):
            return {"conviction": {"margin_of_safety": 30}}

    context = assessment_pipeline.build_context(
        "OPP-1", "TEST", tmp_path, SQLite(), Knowledge(),
        JournalRepository(tmp_path / "idos-journal"), cache_only=True,
    )

    assert context["current_price"] is None
    assert context["price_margin"] is None
    assert context["margin_of_safety"] is None
    result = ValuationAssessmentEngine().evaluate(context)
    assert not any("Price target upside" in item["detail"] for item in result.findings)
    rule = assessment_pipeline._eval_valuation(context)
    assert rule.passed is False
    assert "unavailable" in rule.details
