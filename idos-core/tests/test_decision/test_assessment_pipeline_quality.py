from idos.decision.assessment_pipeline import _financial_data_quality


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
