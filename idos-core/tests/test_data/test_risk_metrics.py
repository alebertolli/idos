import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from idos.data.risk_metrics import enrich_price_risk, normalize_debt_equity
from idos.decision.assessment_pipeline import _load_financial_data, _normalize_decimal_pcts
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.workers.ai.research_worker import ResearchWorker

AS_OF = date(2026, 10, 18)


def history():
    days = []
    day = AS_OF
    while len(days) < 91:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    prices = [100.0]
    for n in range(90):
        prices.append(prices[-1] * math.exp(0.01 if n % 2 else -0.01))
    return {"price_history": prices, "price_history_dates": list(reversed(days)),
            "price_history_source": "fixture", "price_history_adjustment": "split_and_dividend_adjusted"}


def test_known_annualized_sample_volatility_and_real_zero():
    data = enrich_price_risk(history(), as_of=AS_OF)
    assert data["volatility_90d"] == pytest.approx(100 * math.sqrt(252 * 90 * 0.01**2 / 89))
    assert data["risk_metric_provenance"]["volatility_90d"]["observations"] == 91
    flat = history()
    flat["price_history"] = [100.0] * 91
    assert enrich_price_risk(flat, as_of=AS_OF)["volatility_90d"] == 0
    assert flat["_risk_metric_availability"]["volatility_90d"] is True


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True, "invalid", None])
def test_bad_price_is_not_dropped_or_imputed(bad):
    data = history()
    data["price_history"][45] = bad
    enrich_price_risk(data, as_of=AS_OF)
    assert data["volatility_90d"] is None
    assert data["_risk_metric_availability"]["volatility_90d"] is False


@pytest.mark.parametrize("issue", ["short", "mismatch", "duplicate", "reverse", "weekly", "stale", "future", "adjustment"])
def test_unusable_history_remains_unknown(issue):
    data = history()
    if issue == "short": data["price_history"] = data["price_history"][:-1]
    if issue == "mismatch": data["price_history_dates"] = []
    if issue == "duplicate": data["price_history_dates"][-1] = data["price_history_dates"][-2]
    if issue == "reverse": data["price_history_dates"].reverse()
    if issue == "weekly": data["price_history_dates"] = [(AS_OF - timedelta(days=7 * i)).isoformat() for i in reversed(range(91))]
    if issue in {"stale", "future"}:
        shift = timedelta(days=-10 if issue == "stale" else 10)
        data["price_history_dates"] = [(date.fromisoformat(x) + shift).isoformat() for x in data["price_history_dates"]]
    if issue == "adjustment": data.pop("price_history_adjustment")
    assert enrich_price_risk(data, as_of=AS_OF)["volatility_90d"] is None


@pytest.mark.parametrize("source,value,expected", [("stockanalysis.com", 1.07, 1.07), ("stockanalysis.com", 3.5, 3.5), ("yahoo_finance", 107, 1.07), ("yahoo_finance", 0.5, .005)])
def test_debt_equity_source_units_and_idempotence(source, value, expected):
    for normalizer in (normalize_debt_equity, _normalize_decimal_pcts, ResearchWorker._normalize_decimal_pcts):
        data = normalizer({"source": source, "debt_equity_ratio": value})
        assert data["debt_equity_ratio"] == expected
        assert normalizer(data)["debt_equity_ratio"] == expected


def test_cache_to_risk_engine_uses_adjusted_history_and_ratio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from idos.timezone import AR_TZ
    from datetime import datetime
    today = datetime.now(AR_TZ).date()
    data = history()
    delta = today - AS_OF
    data["price_history_dates"] = [(date.fromisoformat(x) + delta).isoformat() for x in data["price_history_dates"]]
    data.update(source="stockanalysis.com", debt_equity_ratio=1.07, current_ratio=.69)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "TEST.json").write_text(json.dumps(data), encoding="utf-8")
    financial = _load_financial_data("TEST", object())
    result = RiskAssessmentEngine().evaluate({"knowledge_base": {"dynamic": {
        "metrics": {"debt_to_equity": financial["debt_equity_ratio"], "current_ratio": financial["current_ratio"], "volatility_90d": financial["volatility_90d"]},
        "metric_availability": financial["_risk_metric_availability"],
    }}})
    assert result.recommendation == "MODERATE_RISK"
    assert not any(r["type"] == "DATA_QUALITY" for r in result.risks)
    assert {r["type"] for r in result.risks} == {"LEVERAGE", "LIQUIDITY"}
    assert not any(f.get("detail") == "Low leverage" for f in result.findings)


def test_systematic_missing_volatility_is_unknown():
    report = ResearchWorker._build_systematic_ddd("XLF", {"signal": {"momentum": 1}}, {})
    assert "UNKNOWN" in report["resumen_ejecutivo"]


def test_daily_selection_includes_research_deduplicates_and_bounds(tmp_path):
    spec = importlib.util.spec_from_file_location("refresh_daily_data", Path(__file__).resolve().parents[3] / "scripts/refresh_daily_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from idos.data.journal import JournalRepository
    repo = JournalRepository(tmp_path / "idos-journal")
    repo.save_opportunity("VIST", {"id": "ONE", "status": "UNDER_RESEARCH"})
    repo.save_opportunity("VIST", {"id": "TWO", "status": "APPROVED"})
    repo.save_opportunity("OLD", {"id": "OLD", "status": "REJECTED"})
    assert module.select_tickers(tmp_path) == ["VIST"]
    assert module.select_tickers(tmp_path, "vist, VIST, RACE") == ["RACE", "VIST"]
    with pytest.raises(ValueError): module.select_tickers(tmp_path, "bad;command")


@pytest.mark.parametrize("bad", [None, True, "bad", float("nan"), float("inf"), -1])
def test_invalid_debt_equity_cannot_become_low_leverage(bad):
    data = _normalize_decimal_pcts({"source": "stockanalysis.com", "debt_equity_ratio": bad})
    assert data["_risk_metric_availability"]["debt_to_equity"] is False


def test_refresh_produces_auditable_price_risk_without_external_calls(tmp_path, monkeypatch):
    import pandas as pd
    from types import SimpleNamespace
    import yfinance
    from idos.workers.data.refresh_worker import DataRefreshWorker
    from idos.timezone import AR_TZ
    from datetime import datetime
    monkeypatch.chdir(tmp_path)
    data = history()
    delta = datetime.now(AR_TZ).date() - AS_OF
    dates = [(date.fromisoformat(x) + delta).isoformat() for x in data["price_history_dates"]]
    frame = pd.DataFrame({"Close": data["price_history"], "Volume": [1000] * 91}, index=pd.to_datetime(dates))
    def adjusted_history(**kwargs):
        assert kwargs["auto_adjust"] is True
        return frame
    fake = SimpleNamespace(info={}, history=adjusted_history)
    monkeypatch.setattr(yfinance, "Ticker", lambda _ticker: fake)
    worker = DataRefreshWorker()
    monkeypatch.setattr(worker.cache, "get", lambda *_: None)
    monkeypatch.setattr(worker, "_save_company_info", lambda *_: None)
    monkeypatch.setattr(worker.retry, "execute", lambda *_: SimpleNamespace(status="success", output={"source": "stockanalysis.com", "debt_equity_ratio": 1.07}))
    result = worker.run({"tickers": ["TEST"]})
    assert result["tickers_processed"] == 1
    cached = json.loads((tmp_path / "cache/TEST.json").read_text(encoding="utf-8"))
    assert cached["debt_equity_ratio"] == 1.07
    assert cached["volatility_90d"] > 0
    assert cached["risk_metric_provenance"]["volatility_90d"]["source"] == "yfinance"
    assert cached["risk_metric_provenance"]["volatility_90d"]["status"] == "OBSERVED"
