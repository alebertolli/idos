from idos.discovery.financial_evidence import reconcile_metric_observations
from idos.workers.data.refresh_worker import DataRefreshWorker


def test_refresh_emits_filed_sec_evidence_and_blocks_missing_report_dates():
    sources = {
        "sec_edgar": {
            "operating_margin_pct": 20.0,
            "financial_data_observed_at": "2026-10-15T12:00:00+00:00",
            "financial_metric_metadata": {
                "operating_margin_pct": {
                    "period_type": "FY",
                    "period_start_date": "2025-01-01",
                    "period_end_date": "2025-12-31",
                    "filed_at": "2026-09-30",
                    "unit": "percentage_points",
                    "currency": "USD",
                    "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                }
            },
        },
        "stockanalysis.com": {
            "operating_margin_pct": 20.0,
            "financial_data_observed_at": "2026-10-15T12:00:00+00:00",
            "financial_metric_metadata": {
                "operating_margin_pct": {
                    "period_type": "TTM",
                    "period_end_date": "2026-09-30",
                    "unit": "percentage_points",
                    "source_url": "https://stockanalysis.com/stocks/test/financials/",
                }
            },
        },
    }

    observations, exclusions = DataRefreshWorker._build_metric_observations(sources)

    assert observations["operating_margin_pct"] == [{
        "source_id": "sec_edgar",
        "value": 20.0,
        "unit": "percent",
        "currency": "USD",
        "period": "FY:2025-01-01/2025-12-31",
        "reported_at": "2026-09-30",
        "observed_at": "2026-10-15T12:00:00+00:00",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    }]
    assert exclusions["operating_margin_pct"][0]["source_id"] == "stockanalysis.com"
    assert "reported_at" in exclusions["operating_margin_pct"][0]["missing_fields"]

    result = reconcile_metric_observations(
        observations["operating_margin_pct"],
        expected_unit="percent",
        expected_currency=None,
        minimum_sources=2,
        conflict_tolerance_pct=20,
        stale_after_days=120,
        now="2026-10-21T00:00:00+00:00",
    )
    assert result["status"] == "insufficient_sources"
    assert result["source_evidence"][0]["source_id"] == "sec_edgar"
