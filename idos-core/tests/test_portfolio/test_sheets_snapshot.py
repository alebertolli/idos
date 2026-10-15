import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from idos.portfolio.audit import PortfolioAuditError, audit_portfolio
from idos.portfolio.sheets_snapshot import snapshot_from_sheets_values


def sheets_export():
    return {
        "Snapshot": [
            ["Cartera privada"],
            ["snapshot_id", "SNP-2026-10-15"],
            ["as_of", "2026-10-15"],
            ["base_currency", "USD"],
            ["source_version", "1.0"],
        ],
        "Positions": [
            ["position_id", "account_id", "instrument_id", "issuer", "economic_cluster",
             "strategy_id", "sleeve", "sector", "country", "argentina_risk_bucket",
             "currency", "market_value", "source_ref"],
            ["p-usd", "acct-a", "BOND-A", "Issuer A", "Issuer A", "CREDIT", "CORE_2",
             "Fixed Income", "US", "NONE", "USD", 6000, "statement-1"],
            ["p-ars", "acct-a", "BOND-B", "Issuer B", "Issuer B", "CREDIT", "CORE_2",
             "Fixed Income", "AR", "SOVEREIGN", "ARS", 4000000, "statement-2"],
            ["", "", "", "", "", "", "", "", "", "", "", ""],
        ],
        "Cash": [
            ["cash_id", "account_id", "currency", "balance", "source_ref"],
            ["cash-usd", "acct-a", "USD", 500, "cash-statement-1"],
            ["cash-ars", "acct-a", "ARS", 1000000, "cash-statement-2"],
        ],
        "Obligations": [
            ["obligation_id", "account_id", "due_date", "currency", "amount", "status", "source_ref"],
            ["bill-1", "acct-a", "2026-11-15", "ARS", 500000, "PENDING", "bill-1-ref"],
        ],
        "FX": [
            ["currency", "to_base", "as_of", "source_ref"],
            ["USD", 1, "2026-10-15", "fx-usd"],
            ["ARS", 0.001, "2026-10-14", "fx-ars"],
        ],
    }


def test_sheets_export_becomes_auditable_snapshot_with_separate_liquidity():
    snapshot = snapshot_from_sheets_values(sheets_export())
    report = audit_portfolio(snapshot)

    assert snapshot["snapshot_id"] == "SNP-2026-10-15"
    assert report["total_market_value"] == 10000
    assert report["snapshot_id"] == "SNP-2026-10-15"
    assert report["source_version"] == "1.0"
    assert report["exposures_pct"]["issuer"] == {"Issuer A": 60, "Issuer B": 40}
    assert report["liquidity"]["cash_total_base"] == 1500
    assert report["liquidity"]["pending_obligations_base"] == 500
    assert report["liquidity"]["net_liquidity_base"] == 1000
    assert report["liquidity"]["obligations_due_base"]["31_to_90_days"] == 500
    assert report["liquidity"]["financial_assets_less_obligations_base"] == 11000
    assert report["liquidity"]["allocation_authorized"] is False


def test_accepts_native_numeric_schema_version_and_sheets_date_serials():
    values = sheets_export()
    sheets_epoch = date(1899, 12, 30)
    values["Snapshot"][2][1] = (date(2026, 10, 15) - sheets_epoch).days
    values["Snapshot"][4][1] = 1
    values["FX"][1][2] = (date(2026, 10, 15) - sheets_epoch).days
    values["FX"][2][2] = (date(2026, 10, 14) - sheets_epoch).days
    values["Obligations"][1][2] = (date(2026, 11, 15) - sheets_epoch).days

    snapshot = snapshot_from_sheets_values(values)

    assert snapshot["as_of"] == "2026-10-15"
    assert snapshot["obligations"][0]["due_date"] == "2026-11-15"


@pytest.mark.parametrize("mutate, error", [
    (lambda s: s["Positions"].append(s["Positions"][1]), "duplicate position_id"),
    (lambda s: s["Positions"][2].__setitem__(10, "EUR"), "missing FX rate for EUR"),
    (lambda s: s["FX"][2].__setitem__(2, "2026-10-16"), "after snapshot.as_of"),
    (lambda s: s["Cash"][1].__setitem__(4, ""), "source_ref is required"),
    (lambda s: s["FX"][2].__setitem__(0, "USD"), "duplicate FX currency"),
    (lambda s: s["Obligations"][1].__setitem__(5, "PAID"), "status must be PENDING"),
    (lambda s: s["Positions"][1].__setitem__(11, "NaN"), "finite positive number"),
    (lambda s: s["Cash"][1].__setitem__(0, 123), r"Cash\[0\]\.cash_id is required"),
])
def test_rejects_invalid_sheets_contract(mutate, error):
    values = sheets_export()
    mutate(values)
    with pytest.raises(PortfolioAuditError, match=error):
        snapshot_from_sheets_values(values)


def test_cli_end_to_end_accepts_values_export_and_writes_only_private_report(tmp_path: Path):
    source = tmp_path / "private-sheets-export.json"
    output = tmp_path / "private-report.json"
    source.write_text(json.dumps({"sheets": sheets_export()}), encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "audit_portfolio.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["total_market_value"] == 10000
    assert report["liquidity"]["net_liquidity_base"] == 1000
    assert "acct-a" not in json.dumps(report)
