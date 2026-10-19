import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scripts.ddd_research as ddd_research


def test_research_worker_failure_marks_run_failed_and_returns_nonzero(
    tmp_path: Path, monkeypatch
):
    models_path = tmp_path / "idos-config" / "models.yml"
    models_path.parent.mkdir(parents=True)
    models_path.write_text("llm: {}\n", encoding="utf-8")
    opportunity_dir = (
        tmp_path / "idos-journal" / "companies" / "TEST" / "case_file"
        / "opportunities" / "OPP-TEST-001"
    )
    opportunity_dir.mkdir(parents=True)
    (opportunity_dir / "opportunity.yml").write_text(
        yaml.safe_dump({
            "id": "OPP-TEST-001",
            "ticker": "TEST",
            "status": "SCREENED",
            "conviction": {"overall": 55},
        }),
        encoding="utf-8",
    )

    service = object()
    captured_config = {}
    captured_service_path = {}

    def fake_llm_service(config_path=None):
        captured_service_path["path"] = config_path
        return service

    class FailedResearchWorker:
        def __init__(self, config):
            captured_config.update(config)

        def run(self, context):
            return {
                "status": "ddd_failed",
                "error": "Failed to parse JSON",
            }

    monkeypatch.setattr(
        "idos.workers.ai.research_worker.ResearchWorker", FailedResearchWorker
    )
    monkeypatch.setattr("idos.ai.service.LLMService", fake_llm_service)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FORCE", "false")
    monkeypatch.setenv("TICKER", "")
    monkeypatch.setenv("EVENT_TYPE", "monthly")
    monkeypatch.chdir(tmp_path)

    exit_code = ddd_research.main()

    results = json.loads((tmp_path / "cache" / "ddd_results.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert results["status"] == "failed"
    assert results["total"] == 1
    assert results["errors"] == [{
        "ticker": "TEST",
        "opp_id": "OPP-TEST-001",
        "status": "ddd_failed",
        "error": "Failed to parse JSON",
        "errors": [],
    }]
    assert captured_service_path["path"] == str(models_path.relative_to(tmp_path))
    assert captured_config["llm_service"] is service
    assert captured_config["prompts_path"] == "idos-config/prompts"


def test_combined_ddd_digest_persists_results(tmp_path, monkeypatch):
    import json
    from scripts.ddd_digest import main

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ddd_results.json").write_text(json.dumps({
        "total": 1,
        "processed": [{"ticker": "XLF", "opp_id": "OPP-XLF", "status": "completed", "score": 23}],
        "assessments": [{"ticker": "XLF", "opp_id": "OPP-XLF", "recommendation": "WAIT", "board_approved": False}],
        "errors": [],
    }), encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    main()

    digest = (cache / "weekly_digest.md").read_text(encoding="utf-8")
    assert "**XLF**" in digest
    assert "**Assessment completados:** 1" in digest
    assert "**Approved:** 0" in digest


def test_selected_research_count_survives_assessment_and_digest(tmp_path, monkeypatch):
    from scripts import ddd_assessment, ddd_digest

    opportunity = tmp_path / "idos-journal/companies/XLF/case_file/opportunities/OPP-XLF"
    opportunity.mkdir(parents=True)
    (opportunity / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-XLF", "ticker": "XLF", "status": "SCREENED",
    }), encoding="utf-8")

    class Research:
        def __init__(self, config):
            pass

        def run(self, context):
            return {"status": "completed", "score": 23}

    monkeypatch.setattr("idos.workers.ai.research_worker.ResearchWorker", Research)
    monkeypatch.setattr("idos.ai.service.LLMService", lambda *args: object())
    monkeypatch.setattr("idos.decision.assessment_pipeline.run_full_pipeline", lambda *args, **kwargs: {
        "ticker": "XLF", "opp_id": "OPP-XLF", "recommendation": "WAIT", "board_approved": False,
    })
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FORCE", "false")
    monkeypatch.setenv("TICKER", "XLF")
    monkeypatch.chdir(tmp_path)
    assert ddd_research.main() == 0
    ddd_assessment.main()
    ddd_digest.main()
    result = json.loads((tmp_path / "cache/ddd_results.json").read_text(encoding="utf-8"))
    assert result["total"] == len(result["processed"]) == len(result["assessments"]) == 1
    digest = (tmp_path / "cache/weekly_digest.md").read_text(encoding="utf-8")
    assert "**Total encontradas:** 1" in digest


def test_assessment_only_replaces_selected_persisted_assessment_without_research(tmp_path, monkeypatch):
    from scripts import ddd_assessment

    opp_id = "OPP-ASML"
    opportunity = tmp_path / "idos-journal/companies/ASML/case_file/opportunities" / opp_id
    opportunity.mkdir(parents=True)
    (opportunity / "ddd_report.yml").write_text("ticker: ASML\ntesis_inversion: thesis\n", encoding="utf-8")
    previous = {
        "ticker": "ASML",
        "opp_id": opp_id,
        "status": "completed",
        "recommendation": "BLOCKED",
        "assessments": {"PortfolioAssessmentEngine": 90},
    }
    other = {"ticker": "AAPL", "opp_id": "OPP-AAPL", "recommendation": "WAIT"}
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ddd_results.json").write_text(json.dumps({
        "processed": [], "assessments": [previous.copy(), other.copy()], "errors": [], "total": 2,
    }), encoding="utf-8")

    calls = []
    def run_assessment(selected_id, selected_ticker, *_args, **_kwargs):
        calls.append((selected_id, selected_ticker))
        return {
            "ticker": selected_ticker,
            "opp_id": selected_id,
            "status": "completed",
            "recommendation": "BLOCKED",
            "assessments": {"PortfolioAssessmentEngine": 50},
        }

    monkeypatch.setattr("idos.decision.assessment_pipeline.run_full_pipeline", run_assessment)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TICKER", "ASML")
    monkeypatch.setenv("REASSESS_EXISTING", "true")
    monkeypatch.chdir(tmp_path)

    ddd_assessment.main()

    saved = json.loads((cache / "ddd_results.json").read_text(encoding="utf-8"))
    assert calls == [(opp_id, "ASML")]
    assert len(saved["assessments"]) == 2
    assert saved["assessments"][0]["assessments"]["PortfolioAssessmentEngine"] == 50
    assert saved["assessments"][1] == other


def test_assessment_only_requires_one_ticker(tmp_path, monkeypatch):
    from scripts import ddd_assessment

    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TICKER", "ASML,AAPL")
    monkeypatch.setenv("REASSESS_EXISTING", "true")
    with pytest.raises(ValueError, match="exactly one selected ticker"):
        ddd_assessment.main()


def test_assessment_only_skips_when_persisted_research_is_missing(tmp_path, monkeypatch):
    from scripts import ddd_assessment

    previous = {"ticker": "ASML", "opp_id": "OPP-ASML", "recommendation": "BLOCKED"}
    cache = tmp_path / "cache"
    cache.mkdir()
    results_path = cache / "ddd_results.json"
    results_path.write_text(json.dumps({"processed": [], "assessments": [previous], "errors": []}), encoding="utf-8")
    monkeypatch.setattr(
        "idos.decision.assessment_pipeline.run_full_pipeline",
        lambda *_args, **_kwargs: pytest.fail("must not assess without persisted Research"),
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TICKER", "ASML")
    monkeypatch.setenv("REASSESS_EXISTING", "true")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="persisted Research"):
        ddd_assessment.main()

    saved = json.loads(results_path.read_text(encoding="utf-8"))
    assert saved["assessments"] == [previous]
    assert saved["errors"] == []


def test_event_research_is_strategy_configured_and_never_applies_to_systematic(tmp_path):
    from idos.strategy.catalog import StrategyCatalog

    config = tmp_path / "idos-config" / "strategies.yml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"strategies": {
        "COMPOUNDER": {
            "core": "CORE_3_GROWTH", "sleeve": "HIGH_CONVICTION",
            "thesis_type": "STRATEGIC", "discovery_profile": "compounder",
            "research_profile": "strategic", "entry_policy": "VALUATION_ZONE",
            "enabled": True,
            "parameters": {"research": {"event_triggers": ["quarterly_results"]}},
        },
        "MOMENTUM_ETF": {
            "core": "CORE_3_GROWTH", "sleeve": "SYSTEMATIC_RETURN",
            "thesis_type": "SYSTEMATIC", "discovery_profile": "momentum_monthly",
            "research_profile": "systematic", "entry_policy": "SIGNAL_REBALANCE",
            "enabled": True,
            "parameters": {"research": {"event_triggers": ["quarterly_results"]}},
        },
        "DISABLED": {
            "core": "CORE_3_GROWTH", "sleeve": "HIGH_CONVICTION",
            "thesis_type": "STRATEGIC", "discovery_profile": "compounder",
            "research_profile": "strategic", "entry_policy": "VALUATION_ZONE",
            "enabled": False,
            "parameters": {"research": {"event_triggers": ["quarterly_results"]}},
        },
    }}), encoding="utf-8")
    catalog = StrategyCatalog(config)

    assert ddd_research._configured_event_trigger(
        {"strategy_id": "COMPOUNDER"}, "quarterly-results", catalog,
    ) == "quarterly_results"
    assert ddd_research._configured_event_trigger(
        {"strategy_id": "COMPOUNDER"}, "guidance-change", catalog,
    ) is None
    assert ddd_research._configured_event_trigger(
        {"strategy_id": "MOMENTUM_ETF"}, "quarterly-results", catalog,
    ) is None
    assert ddd_research._configured_event_trigger(
        {"strategy_id": "DISABLED"}, "quarterly-results", catalog,
    ) is None


def test_material_event_researches_approved_but_not_terminal_opportunities(monkeypatch):
    monkeypatch.setattr(ddd_research, "SKIP_TICKERS", {"ASML"})
    approved = {"ticker": "ASML", "status": "APPROVED"}
    terminal = {"ticker": "ASML", "status": "WATCHLIST"}

    should_research, force_reprocess, reason = ddd_research._needs_research(
        approved, False, event_trigger="quarterly_results",
    )
    terminal_research, _, _ = ddd_research._needs_research(
        terminal, False, event_trigger="quarterly_results",
    )

    assert should_research is True
    assert force_reprocess is True
    assert "quarterly_results" in reason
    assert terminal_research is False


def test_event_preview_researches_only_exact_buylist_entry_for_configured_strategy(tmp_path, monkeypatch):
    from scripts import ddd_research as research_script

    config = tmp_path / "idos-config" / "strategies.yml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"strategies": {
        "COMPOUNDER": {
            "core": "CORE_3_GROWTH", "sleeve": "HIGH_CONVICTION",
            "thesis_type": "STRATEGIC", "discovery_profile": "compounder",
            "research_profile": "strategic", "entry_policy": "VALUATION_ZONE",
            "enabled": True,
            "parameters": {"research": {"event_triggers": ["quarterly_results"]}},
        },
    }}), encoding="utf-8")
    opportunity_root = tmp_path / "idos-journal/companies/ASML/case_file/opportunities"
    opportunity_root.mkdir(parents=True)
    for opp_id in ("OPP-BUYLIST", "OPP-OTHER"):
        opp_dir = opportunity_root / opp_id
        opp_dir.mkdir()
        (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
            "id": opp_id, "ticker": "ASML", "strategy_id": "COMPOUNDER",
            "status": "APPROVED",
        }), encoding="utf-8")
    buylist = tmp_path / "idos-journal/portfolio/buylist.yml"
    buylist.parent.mkdir(parents=True)
    buylist.write_text(yaml.safe_dump({"entries": [{
        "ticker": "ASML", "opp_id": "OPP-BUYLIST",
    }]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TICKER", "ASML")
    monkeypatch.setenv("FORCE", "true")
    monkeypatch.setenv("EVENT_TYPE", "quarterly-results")
    monkeypatch.setenv("REVIEW_BUYLIST", "false")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    event_payload = tmp_path / "github-event.json"
    event_payload.write_text(json.dumps({"inputs": {
        "event_date": "2026-10-14",
        "event_source_name": "ASML Investor Relations",
        "event_source_url": "https://www.asml.com/en/news/press-releases/2026/q3-results",
        "event_summary": "Quarterly results published; verify figures in the primary release.",
    }}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload))

    research_script.preview()

    preview = json.loads((tmp_path / "cache/ddd_preview.json").read_text(encoding="utf-8"))
    assert [(entry["ticker"], entry["opp_id"]) for entry in preview["selected"]] == [
        ("ASML", "OPP-BUYLIST"),
    ]
    assert preview["selected"][0]["trigger_type"] == "quarterly_results"
    assert preview["selected"][0]["force_reprocess"] is True
    assert preview["selected"][0]["event_evidence"]["source_name"] == "ASML Investor Relations"


def test_material_event_without_evidence_fails_closed_even_when_force_is_true(tmp_path, monkeypatch):
    config = tmp_path / "idos-config" / "strategies.yml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"strategies": {
        "COMPOUNDER": {
            "core": "CORE_3_GROWTH", "sleeve": "HIGH_CONVICTION",
            "thesis_type": "STRATEGIC", "discovery_profile": "compounder",
            "research_profile": "strategic", "entry_policy": "VALUATION_ZONE",
            "enabled": True,
            "parameters": {"research": {"event_triggers": ["quarterly_results"]}},
        },
    }}), encoding="utf-8")
    opp_dir = tmp_path / "idos-journal/companies/ASML/case_file/opportunities/OPP-ASML"
    opp_dir.mkdir(parents=True)
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-ASML", "ticker": "ASML", "strategy_id": "COMPOUNDER",
        "status": "UNDER_DEEP_DD",
    }), encoding="utf-8")
    event_payload = tmp_path / "github-event.json"
    event_payload.write_text(json.dumps({"inputs": {}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TICKER", "ASML")
    monkeypatch.setenv("FORCE", "true")
    monkeypatch.setenv("EVENT_TYPE", "quarterly-results")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload))

    assert ddd_research.preview() == 2
    preview = json.loads((tmp_path / "cache/ddd_preview.json").read_text(encoding="utf-8"))
    assert preview["selected"] == []
    assert "occurred_at" in preview["skipped"][0]["reason"]


def test_buylist_re_review_requires_manual_single_ticker_and_selects_exact_entry(tmp_path, monkeypatch):
    opportunity_root = tmp_path / "idos-journal/companies/TEST/case_file/opportunities"
    opportunity_root.mkdir(parents=True)
    for opp_id in ("OPP-APPROVED", "OPP-OTHER"):
        path = opportunity_root / opp_id
        path.mkdir()
        (path / "opportunity.yml").write_text(yaml.safe_dump({
            "id": opp_id,
            "ticker": "TEST",
            "status": "UNDER_DEEP_DD",
            "conviction": {"overall": 75},
        }), encoding="utf-8")
    buylist_path = tmp_path / "idos-journal/portfolio/buylist.yml"
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [
        {"ticker": "TEST", "opp_id": "OPP-APPROVED"},
    ]}), encoding="utf-8")
    positions_dir = tmp_path / "idos-journal/paper/positions"
    positions_dir.mkdir(parents=True)
    (positions_dir / "AAPL.yml").write_text(yaml.safe_dump({"ticker": "AAPL"}), encoding="utf-8")

    selected = []

    class Research:
        def __init__(self, config):
            pass

        def run(self, context):
            selected.append(context)
            return {"status": "completed", "score": 75}

    monkeypatch.setattr("idos.workers.ai.research_worker.ResearchWorker", Research)
    monkeypatch.setattr("idos.ai.service.LLMService", lambda *args: object())
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FORCE", "true")
    monkeypatch.setenv("TICKER", "TEST")
    monkeypatch.setenv("EVENT_TYPE", "manual")
    monkeypatch.setenv("REVIEW_BUYLIST", "true")
    monkeypatch.chdir(tmp_path)

    ddd_research.preview()
    preview = json.loads((tmp_path / "cache/ddd_preview.json").read_text(encoding="utf-8"))
    assert [(item["ticker"], item["opp_id"]) for item in preview["selected"]] == [
        ("TEST", "OPP-APPROVED"),
    ]

    assert ddd_research.main() == 0
    results = json.loads((tmp_path / "cache/ddd_results.json").read_text(encoding="utf-8"))
    assert [(item["ticker"], item["opp_id"]) for item in selected] == [("TEST", "OPP-APPROVED")]
    assert selected[0]["force_reprocess"] is True
    assert results["skipped"] == [{
        "opp_id": "OPP-OTHER", "ticker": "TEST", "status": "UNDER_DEEP_DD",
        "reason": "in BUY_LIST/PORTFOLIO; explicit re-review not selected",
    }]
    assert all(item["ticker"] != "AAPL" for item in results["processed"])


def test_buylist_re_review_rejects_nonmanual_or_unbounded_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("FORCE", "true")
    monkeypatch.setenv("TICKER", "TEST,AAPL")
    monkeypatch.setenv("EVENT_TYPE", "manual")
    monkeypatch.setenv("REVIEW_BUYLIST", "true")
    monkeypatch.chdir(tmp_path)

    assert ddd_research.main() == 2


def test_buylist_re_review_is_opt_in_and_pages_workflow_run_is_main_only():
    repository_root = Path(__file__).resolve().parents[2]
    ddd_workflow = yaml.load(
        (repository_root / ".github/workflows/ddd-pipeline.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    pages_workflow = yaml.load(
        (repository_root / ".github/workflows/gh-pages.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    input_config = ddd_workflow["on"]["workflow_dispatch"]["inputs"]["review_buylist"]
    assert input_config["type"] == "boolean"
    assert input_config["default"] == "false"
    assert pages_workflow["on"]["workflow_run"]["branches"] == ["main"]


def test_assessment_only_workflow_runs_assessment_but_skips_research_and_monthly():
    repository_root = Path(__file__).resolve().parents[2]
    workflow = yaml.load(
        (repository_root / ".github/workflows/ddd-pipeline.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = {step["name"]: step for step in workflow["jobs"]["ddd"]["steps"] if step.get("name")}

    assert "assessment_only != 'true'" in steps["STEP 2 - ResearchWorker (DDD + AOIF + Hypothesis)"]["if"]
    assert steps["STEP 3-7 - Assessment Engines + Conviction + Rules + Board + Entry"]["if"] == (
        "github.event.inputs.preview_only != 'true'"
    )
    assert steps["STEP 3-7 - Assessment Engines + Conviction + Rules + Board + Entry"]["env"][
        "REASSESS_EXISTING"
    ] == "${{ inputs.assessment_only || false }}"
    assert "assessment_only != 'true'" in steps[
        "STEP 8 - Monthly Re-Assessment (Thesis + Conviction + Portfolio)"
    ]["if"]
