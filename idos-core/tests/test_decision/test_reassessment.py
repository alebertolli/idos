import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import requests
import yaml
import yfinance

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.decision.assessment_pipeline import build_context

ROOT = Path(__file__).resolve().parents[3]


def runner():
    spec = importlib.util.spec_from_file_location("reassess_opportunities", ROOT / "scripts/reassess_opportunities.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(base):
    shutil.copytree(ROOT / "idos-config", base / "idos-config")
    journal = JournalRepository(base / "idos-journal")
    journal.save_opportunity("TEST", {"id": "OPP-TEST", "ticker": "TEST", "status": "UNDER_RESEARCH",
        "strategy_id": "COMPOUNDER", "strategy_version": "fixture-v1", "entry_policy": "MANUAL_REVIEW",
        "last_research_at": "2026-10-17T10:00:00-03:00"})
    case = journal.opportunity_path("TEST", "OPP-TEST")
    report = {"opp_id": "OPP-TEST", "tesis_inversion": "Synthetic thesis requiring source review",
              "score_general": 70, "generated_at": "2026-10-17T10:00:00-03:00",
              "dominio_catalizadores": [], "dominio_riesgos": []}
    (case / "ddd_report.yml").write_text(yaml.safe_dump(report), encoding="utf-8")
    (base / "cache").mkdir()
    (base / "cache/TEST.json").write_text(json.dumps({"source": "stockanalysis.com", "price": 100,
        "price_target_avg": 120, "current_ratio": 1.2, "debt_equity_ratio": 1.07,
        "roic_pct": 15, "revenue_growth_pct": 12, "operating_margin_pct": 20,
        "pe_ratio": 10}), encoding="utf-8")
    return journal, case


def test_reassessment_persists_board_author_and_preserves_research(tmp_path, monkeypatch):
    journal, case = seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Reassessment must not request providers")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(yfinance, "Ticker", forbidden)
    report_before = (case / "ddd_report.yml").read_bytes()
    old_dir = case / "decisions"
    old_dir.mkdir()
    old_decision = old_dir / "DEC-LEGACY.yml"
    old_decision.write_text("id: DEC-LEGACY\nauthor: human\n", encoding="utf-8")
    previous = old_decision.read_bytes()
    result = runner().reassess(tmp_path, "TEST")
    assert result["errors"] == []
    assert len(result["results"]) == 1
    resolution = yaml.safe_load((case / "board_resolution.yml").read_text(encoding="utf-8"))
    assert resolution["author"] == "board"
    assert resolution["approved"] is False
    updated = journal.load_opportunity("TEST", "OPP-TEST")
    assert updated["last_research_at"] == "2026-10-17T10:00:00-03:00"
    assert updated["last_assessment_at"]
    assert updated["strategy_id"] == "COMPOUNDER"
    assert (case / "ddd_report.yml").read_bytes() == report_before
    assert old_decision.read_bytes() == previous
    proposal = yaml.safe_load((case / "decision_proposal.yml").read_text(encoding="utf-8"))
    assert proposal["assessments"]["RiskAssessmentEngine"]["recommendation"] == "INSUFFICIENT_DATA"


def test_empty_sqlite_preserves_multistrategy_context(tmp_path, monkeypatch):
    journal, case = seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    opp = journal.load_opportunity("TEST", "OPP-TEST")
    opp.update(strategy_id="MULTIBAGGERS", entry_policy="MANUAL_REVIEW", research_profile="multibaggers")
    journal.save_opportunity("TEST", opp)
    sqlite = SQLiteStore(tmp_path / "idos.db")
    context = build_context("OPP-TEST", "TEST", tmp_path, sqlite,
                            KnowledgeRepository(tmp_path / "idos-knowledge"), journal, cache_only=True)
    assert context["strategy_id"] == "MULTIBAGGERS"
    assert context["research_profile"] == "multibaggers"
    assert context["entry_policy"] == "MANUAL_REVIEW"


@pytest.mark.parametrize("selection", ["", "TEST;command", "bad ticker"])
def test_explicit_selection_required(tmp_path, selection):
    with pytest.raises(ValueError): runner().reassess(tmp_path, selection)


def test_failed_report_and_missing_candidate_fail_closed(tmp_path, monkeypatch):
    journal, case = seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = case / "ddd_report.yml"
    report.write_text("research_status: FAILED\ntesis_inversion: stale text\n", encoding="utf-8")
    result = runner().reassess(tmp_path, "TEST,ABSENT")
    assert result["results"] == []
    assert len(result["errors"]) == 2
    assert not (case / "board_resolution.yml").exists()
