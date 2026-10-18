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
        "positions": [
            {"position_id": "bond-credit", "market_value": "6000", "currency": "USD",
             "instrument_id": "BOND-A", "issuer": "Issuer A", "economic_cluster": "Issuer A",
             "strategy_id": "CREDIT", "sleeve": "OPPORTUNITY", "sector": "Sovereign",
             "country": "AR", "argentina_risk_bucket": "SOVEREIGN_SHORT_DURATION"},
            {"position_id": "bond-optionality", "market_value": "4000000", "currency": "ARS",
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
    assert report["risk_audit_status"] == "NOT_ASSESSED"
    assert "credit_default_recovery_risk" in report["risk_dimensions_not_assessed"]
    assert report["allocation_authorized"] is False


def test_missing_classification_is_explicit_and_blocks_completion():
    data = snapshot()
    del data["positions"][0]["economic_cluster"]
    report = audit_portfolio(data)
    assert report["status"] == "REVIEW"
    assert {"position_id": "bond-credit", "field": "economic_cluster"} in report["missing_classifications"]
    assert report["exposures_pct"]["economic_cluster"]["UNKNOWN"] == 60


@pytest.mark.parametrize("change, message", [
    (lambda d: d["fx_to_base"].clear(), "missing FX rate"),
    (lambda d: d["positions"][1].update(position_id="bond-credit"), "duplicate position_id"),
    (lambda d: d["positions"][0].update(market_value="NaN"), "finite positive number"),
    (lambda d: d["positions"][0].update(market_value=-1), "finite positive number"),
])
def test_rejects_unreliable_inputs(change, message):
    data = snapshot()
    change(data)
    with pytest.raises(PortfolioAuditError, match=message):
        audit_portfolio(data)


def test_cli_end_to_end_keeps_input_separate_from_report(tmp_path: Path):
    source = tmp_path / "private-snapshot.json"
    output = tmp_path / "private-report.json"
    source.write_text(json.dumps(snapshot()), encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "audit_portfolio.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["total_market_value"] == 10000
    assert json.loads(output.read_text(encoding="utf-8"))["risk_audit_status"] == "NOT_ASSESSED"
    assert json.loads(source.read_text(encoding="utf-8"))["positions"][0]["market_value"] == "6000"
