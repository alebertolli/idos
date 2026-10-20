from __future__ import annotations

import pytest

from idos.workers.data import sec_edgar
from idos.workers.data.sec_company_facts import normalize_company_facts


def _fact(start: str, end: str, value: float, *, filed: str | None = None, form: str = "10-K") -> dict:
    return {
        "start": start,
        "end": end,
        "val": value,
        "filed": filed or f"{end[:4]}-02-15",
        "form": form,
        "fy": int(end[:4]),
        "fp": "FY",
        "accn": f"0000000000-{end[:4]}-000001",
    }


def _payload(*, operating_start="2025-01-01") -> dict:
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [
                        _fact("2024-01-01", "2024-12-31", 1000),
                        _fact("2025-01-01", "2025-12-31", 1200),
                    ]}
                },
                "OperatingIncomeLoss": {
                    "units": {"USD": [
                        _fact(operating_start, "2025-12-31", 240),
                    ]}
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [_fact("2025-01-01", "2025-12-31", 310)]}
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {"USD": [_fact("2025-01-01", "2025-12-31", -80)]}
                },
            }
        }
    }


def test_company_facts_normalizes_annual_metrics_with_field_provenance():
    result = normalize_company_facts("aapl", "0000320193", _payload())

    assert result["ticker"] == "AAPL"
    assert result["revenue_growth_pct"] == 20.0
    assert result["operating_margin_pct"] == 20.0
    assert result["fcf"] == 230.0
    assert result["financial_period_type"] == "FY"
    assert result["period_end_date"] == "2025-12-31"
    assert result["financial_metric_metadata"]["revenue_growth_pct"]["unit"] == "percentage_points"
    assert result["financial_metric_metadata"]["fcf"]["currency"] == "USD"
    assert result["financial_metric_metadata"]["fcf"]["components"] == {
        "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
        "capital_expenditures": "PaymentsToAcquirePropertyPlantAndEquipment",
    }
    assert result["data_provenance"]["field_sources"] == {
        "revenue_growth_pct": ["sec_edgar"],
        "operating_margin_pct": ["sec_edgar"],
        "fcf": ["sec_edgar"],
    }


def test_company_facts_does_not_pair_mismatched_periods_or_invent_metrics():
    result = normalize_company_facts("AAPL", "320193", _payload(operating_start="2025-04-01"))

    assert "operating_margin_pct" not in result
    assert result["fcf"] == 230.0
    assert "sec_operating_income_not_comparable_to_revenue" in result["data_quality_warnings"]


def test_company_facts_uses_latest_amended_filing_for_same_period():
    payload = _payload()
    revenue = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    revenue.append(_fact("2025-01-01", "2025-12-31", 1100, filed="2026-03-01", form="10-K/A"))

    result = normalize_company_facts("AAPL", "320193", payload)

    assert result["revenue_growth_pct"] == 10.0
    assert result["financial_metric_metadata"]["revenue_growth_pct"]["form"] == "10-K/A"


def test_company_facts_does_not_calculate_growth_from_nonpositive_prior_revenue():
    payload = _payload()
    revenue = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    revenue[0]["val"] = -1000

    result = normalize_company_facts("AAPL", "320193", payload)

    assert "revenue_growth_pct" not in result
    assert "sec_revenue_not_positive_for_growth" in result["data_quality_warnings"]


def test_worker_requires_declared_sec_contact_before_network_access(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("SEC request must not run without a configured contact")

    monkeypatch.setattr(sec_edgar.requests, "get", fail_if_called)
    worker = sec_edgar.SECEdgarWorker({})

    with pytest.raises(ValueError, match="IDOS_SEC_USER_AGENT"):
        worker.run({"ticker": "AAPL"})
    assert called is False


def test_worker_fetches_companyfacts_using_declared_user_agent(monkeypatch):
    payload = _payload()
    observed_headers = []

    class Response:
        content = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><category term="CIK=0000320193" /></entry></feed>'

        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            return None

        def json(self):
            if "companyfacts" in self.url:
                return payload
            return {"hits": {"hits": []}}

    def fake_get(url, *, headers, timeout):
        observed_headers.append(headers)
        if "browse-edgar" in url:
            response = Response(url)
            response.content = Response.content
            return response
        return Response(url)

    monkeypatch.setattr(sec_edgar.requests, "get", fake_get)
    monkeypatch.setattr(sec_edgar.time, "sleep", lambda _delay: None)
    worker = sec_edgar.SECEdgarWorker({"user_agent": "IDOS test contact@example.org"})

    result = worker.run({"ticker": "AAPL"})

    assert result["revenue_growth_pct"] == 20.0
    assert result["operating_margin_pct"] == 20.0
    assert result["fcf"] == 230.0
    assert observed_headers
    assert all(headers["User-Agent"] == "IDOS test contact@example.org" for headers in observed_headers)


def test_worker_propagates_sec_lookup_network_failure(monkeypatch):
    def fail_lookup(*_args, **_kwargs):
        raise sec_edgar.requests.ConnectionError("SEC unavailable")

    monkeypatch.setattr(sec_edgar.requests, "get", fail_lookup)
    worker = sec_edgar.SECEdgarWorker({"user_agent": "IDOS test contact@example.org"})

    with pytest.raises(sec_edgar.requests.ConnectionError, match="SEC unavailable"):
        worker.run({"ticker": "AAPL"})
