import json
from pathlib import Path
import sys

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
