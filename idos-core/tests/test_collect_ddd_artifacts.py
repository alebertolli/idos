from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.collect_ddd_artifacts import collect_ddd_artifacts


RUN_STARTED_AT = "2026-10-20T18:46:31Z"


def _write_case(base: Path, ticker: str, opp_id: str, generated_at: str) -> Path:
    opportunity = base / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id
    (opportunity / "assessments").mkdir(parents=True, exist_ok=True)
    (opportunity / "ddd_report.yml").write_text(
        yaml.safe_dump({"ticker": ticker, "opp_id": opp_id, "generated_at": generated_at}),
        encoding="utf-8",
    )
    (opportunity / "opportunity.yml").write_text(
        yaml.safe_dump({"ticker": ticker, "id": opp_id, "status": "UNDER_DEEP_DD"}),
        encoding="utf-8",
    )
    (opportunity / "decision_proposal.yml").write_text(
        yaml.safe_dump({"status": "PENDING_HUMAN_REVIEW"}),
        encoding="utf-8",
    )
    (opportunity / "assessments" / "assessment.yml").write_text(
        yaml.safe_dump({"generated_at": generated_at, "recommendation": "WAIT"}),
        encoding="utf-8",
    )
    return opportunity


def test_collector_copies_current_selected_dossier_and_manifest(tmp_path):
    fresh = _write_case(tmp_path, "ALAB", "OPP-FRESH", "2026-10-20T15:48:13-03:00")
    stale = _write_case(tmp_path, "ALAB", "OPP-STALE", "2026-10-20T17:00:00Z")
    unrelated = _write_case(tmp_path, "XLF", "OPP-OTHER", "2026-10-20T15:50:00-03:00")
    (fresh / "private_positions.yml").write_text("must not be copied", encoding="utf-8")

    manifest = collect_ddd_artifacts(
        tmp_path, ["ALAB"], RUN_STARTED_AT, require_output=True,
    )

    assert [(item["ticker"], item["opp_id"]) for item in manifest["opportunities"]] == [
        ("ALAB", "OPP-FRESH")
    ]
    output = tmp_path / "cache" / "ddd-artifact"
    assert (output / "manifest.json").is_file()
    assert (output / "companies" / "ALAB" / "opportunities" / "OPP-FRESH" / "ddd_report.yml").is_file()
    assert (output / "companies" / "ALAB" / "opportunities" / "OPP-FRESH" / "decision_proposal.yml").is_file()
    assert not (output / "companies" / "ALAB" / "opportunities" / "OPP-STALE").exists()
    assert not (output / "companies" / "XLF").exists()
    assert not list(output.rglob("private_positions.yml"))
    assert stale.is_dir() and unrelated.is_dir()


def test_collector_writes_empty_manifest_for_unbounded_scheduled_run(tmp_path):
    manifest = collect_ddd_artifacts(tmp_path, [], RUN_STARTED_AT)

    assert manifest["opportunities"] == []
    assert json.loads((tmp_path / "cache" / "ddd-artifact" / "manifest.json").read_text(encoding="utf-8"))["tickers"] == []


def test_collector_rejects_missing_selected_output(tmp_path):
    with pytest.raises(ValueError, match="No DDD package"):
        collect_ddd_artifacts(tmp_path, ["ALAB"], RUN_STARTED_AT, require_output=True)


def test_collector_rejects_unsafe_tickers_and_output_paths(tmp_path):
    with pytest.raises(ValueError, match="Invalid ticker"):
        collect_ddd_artifacts(tmp_path, ["../PRIVATE"], RUN_STARTED_AT)
    with pytest.raises(ValueError, match="stay inside"):
        collect_ddd_artifacts(tmp_path, ["ALAB"], RUN_STARTED_AT, "../outside")
