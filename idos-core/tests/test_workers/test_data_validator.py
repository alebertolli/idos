from idos.workers.data.validator import DataValidator


def test_cross_validate_single_source():
    v = DataValidator()
    result = v.cross_validate({
        "sa": {"pe_ratio": 25.0, "revenue": 1_000_000},
    })
    assert result["merged_data"]["pe_ratio"] == 25.0
    assert len(result["conflicts"]) == 0


def test_cross_validate_agreement():
    v = DataValidator(tolerance_pct=20)
    result = v.cross_validate({
        "sa": {"pe_ratio": 25.0, "market_cap": 100_000_000_000},
        "yf": {"pe_ratio": 24.0, "market_cap": 105_000_000_000},
    })
    assert abs(result["merged_data"]["pe_ratio"] - 24.5) < 0.1
    assert len(result["conflicts"]) == 0


def test_cross_validate_conflict():
    v = DataValidator(tolerance_pct=10)
    result = v.cross_validate({
        "sa": {"pe_ratio": 15.0},
        "yf": {"pe_ratio": 30.0},
    })
    assert len(result["conflicts"]) >= 1
    assert result["conflicts"][0]["field"] == "pe_ratio"


def test_validate_metrics_warnings():
    v = DataValidator()
    warnings = v.validate_metrics({
        "debt_equity_ratio": 6.0,
        "current_ratio": 0.3,
        "operating_margin_pct": -25.0,
    })
    assert len(warnings) == 3


def test_validate_metrics_clean():
    v = DataValidator()
    warnings = v.validate_metrics({
        "debt_equity_ratio": 1.5,
        "current_ratio": 1.8,
        "operating_margin_pct": 15.0,
    })
    assert len(warnings) == 0


def test_pick_best_prioritizes_stockanalysis():
    v = DataValidator()
    result = v._pick_best({"finviz.com": 20, "stockanalysis.com": 25})
    assert result == 25


def test_merge_non_numeric():
    v = DataValidator()
    result = v.cross_validate({
        "sa": {"sector": "Technology"},
        "yf": {"sector": "Technology"},
    })
    assert result["merged_data"]["sector"] == "Technology"
