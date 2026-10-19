import json
import subprocess
import sys
from pathlib import Path

import pytest

from idos.portfolio.audit import PortfolioAuditError, audit_portfolio


def snapshot():
    return {
        "as_of": "2026-10-15",
        "base_currency": "USD",
        "fx_to_base": {"ARS": "0.001"},
        "fx_provenance": {"ARS": {"as_of": "2026-10-15", "source_ref": "fx-proof"}},
        "positions": [
            {"position_id": "bond-credit", "source_ref": "statement-1", "market_value": "6000", "currency": "USD",
             "instrument_id": "BOND-A", "issuer": "Issuer A", "economic_cluster": "Issuer A",
             "strategy_id": "CREDIT", "sleeve": "OPPORTUNITY", "sector": "Sovereign",
             "country": "AR", "argentina_risk_bucket": "SOVEREIGN_SHORT_DURATION"},
            {"position_id": "bond-optionality", "source_ref": "statement-2", "market_value": "4000000", "currency": "ARS",
             "instrument_id": "BOND-A", "issuer": "Issuer A", "economic_cluster": "Issuer A",
             "strategy_id": "OPTIONALITY", "sleeve": "ALPHA", "sector": "Sovereign",
             "country": "AR", "argentina_risk_bucket": "SOVEREIGN_SHORT_DURATION"},
        ],
    }


def test_consolidates_economic_exposure_across_strategies_and_currencies():
    report = audit_portfolio(snapshot())
    assert report["total_market_value"] == 10000
    assert [p["capital_weight_pct"] for p in report["positions"]] == [60, 40]
    assert report["exposures_pct"]["economic_cluster"] == {"Issuer A": 100}
    assert report["exposures_pct"]["strategy_id"] == {"CREDIT": 60, "OPTIONALITY": 40}
    assert report["status"] == "COMPLETE"
    assert report["audit_scope"] == "CAPITAL_EXPOSURE_ONLY"
    assert report["balance_sheet_status"] == "NOT_PROVIDED"
    assert report["risk_audit_status"] == "NOT_ASSESSED"
    assert "credit_default_recovery_risk" in report["risk_dimensions_not_assessed"]
    assert report["allocation_authorized"] is False


def test_cash_and_pending_obligations_are_included_without_changing_position_exposure():
    data = snapshot()
    data["cash"] = [
        {"cash_id": "cash-usd", "account_id": "acct-1", "source_ref": "cash-1", "currency": "USD", "balance": "1000"},
        {"cash_id": "cash-ars", "account_id": "acct-1", "source_ref": "cash-2", "currency": "ARS", "balance": "1000000"},
    ]
    data["obligations"] = [
        {"obligation_id": "bill-1", "account_id": "acct-1", "source_ref": "bill-ref", "due_date": "2026-10-30",
         "currency": "USD", "amount": "1000", "status": "PENDING"},
    ]

    report = audit_portfolio(data)

    assert report["audit_scope"] == "CAPITAL_AND_BALANCE_SHEET_EXPOSURE"
    assert report["balance_sheet_status"] == "COMPLETE"
    assert report["total_market_value"] == 10000
    assert report["cash_total_base"] == 2000
    assert report["pending_obligations_total_base"] == 1000
    assert report["gross_assets_base"] == 12000
    assert report["net_asset_value_base"] == 11000
    assert report["cash_after_all_pending_obligations_base"] == 1000
    assert report["positions"][0]["capital_weight_pct"] == 60
    assert report["positions"][0]["weight_of_gross_assets_pct"] == 50
    assert report["cash_exposure_pct"]["currency"] == {"ARS": 8.3333, "USD": 8.3333}
    assert report["pending_obligations_pct_of_gross_assets"] == 8.3333
    assert report["risk_audit_status"] == "NOT_ASSESSED"
    assert report["allocation_authorized"] is False


@pytest.mark.parametrize("key, rows, message", [
    ("cash", [{"cash_id": "c1", "account_id": "a", "source_ref": "s", "currency": "USD", "balance": -1}], "non-negative"),
    ("cash", [
        {"cash_id": "c1", "account_id": "a", "source_ref": "s1", "currency": "USD", "balance": 1},
        {"cash_id": "c1", "account_id": "a", "source_ref": "s2", "currency": "USD", "balance": 2},
    ], "duplicate cash_id"),
    ("obligations", [{"obligation_id": "o1", "account_id": "a", "source_ref": "s", "due_date": "2026-10-30",
                      "currency": "USD", "amount": 10, "status": "PAID"}], "must be PENDING"),
    ("obligations", [{"obligation_id": "o1", "account_id": "a", "source_ref": "s", "due_date": "2026-10-30",
                      "currency": "EUR", "amount": 10, "status": "PENDING"}], "missing FX rate"),
    ("obligations", [{"obligation_id": "o1", "account_id": "a", "due_date": "2026-10-30",
                      "currency": "USD", "amount": 10, "status": "PENDING"}], "source_ref is required"),
    ("obligations", [
        {"obligation_id": "o1", "account_id": "a", "source_ref": "s1", "due_date": "2026-10-30",
         "currency": "USD", "amount": 10, "status": "PENDING"},
        {"obligation_id": "o1", "account_id": "a", "source_ref": "s2", "due_date": "2026-10-30",
         "currency": "USD", "amount": 10, "status": "PENDING"},
    ], "duplicate obligation_id"),
])
def test_rejects_invalid_cash_and_obligation_rows(key, rows, message):
    data = snapshot()
    data[key] = rows
    with pytest.raises(PortfolioAuditError, match=message):
        audit_portfolio(data)


def test_missing_classification_is_explicit_and_blocks_completion():
    data = snapshot()
    del data["positions"][0]["economic_cluster"]
    report = audit_portfolio(data)
    assert report["status"] == "REVIEW"
    assert {"position_id": "bond-credit", "field": "economic_cluster"} in report["missing_classifications"]
    assert report["exposures_pct"]["economic_cluster"]["UNKNOWN"] == 60


@pytest.mark.parametrize("change, message", [
    (lambda d: d["fx_to_base"].clear(), "missing FX rate"),
    (lambda d: d["fx_provenance"].clear(), "missing FX provenance"),
    (lambda d: d["fx_provenance"]["ARS"].update(as_of="2026-10-16"), "cannot be after snapshot.as_of"),
    (lambda d: d["positions"][1].update(position_id="bond-credit"), "duplicate position_id"),
    (lambda d: d["positions"][0].pop("source_ref"), "source_ref is required"),
    (lambda d: d["positions"][0].update(market_value="NaN"), "finite positive number"),
    (lambda d: d["positions"][0].update(market_value=-1), "finite positive number"),
])
def test_rejects_unreliable_inputs(change, message):
    data = snapshot()
    change(data)
    with pytest.raises(PortfolioAuditError, match=message):
        audit_portfolio(data)


def test_cli_end_to_end_keeps_input_separate_from_report(tmp_path: Path):
    private_snapshot = snapshot()
    private_snapshot["cash"] = [
        {"cash_id": "cash-1", "account_id": "acct-1", "source_ref": "cash-ref", "currency": "USD", "balance": "1000"},
    ]
    private_snapshot["obligations"] = [
        {"obligation_id": "bill-1", "account_id": "acct-1", "source_ref": "bill-ref", "due_date": "2026-10-30",
         "currency": "USD", "amount": "500", "status": "PENDING"},
    ]
    source = tmp_path / "private-snapshot.json"
    output = tmp_path / "private-report.json"
    source.write_text(json.dumps(private_snapshot), encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "audit_portfolio.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["total_market_value"] == 10000
    assert report["net_asset_value_base"] == 10500
    assert report["balance_sheet_status"] == "COMPLETE"
    assert report["risk_audit_status"] == "NOT_ASSESSED"
    assert report["allocation_authorized"] is False
    assert json.loads(source.read_text(encoding="utf-8"))["positions"][0]["market_value"] == "6000"
