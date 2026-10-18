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
    assert results["errors"] == [{
        "ticker": "TEST",
        "opp_id": "OPP-TEST-001",
        "status": "ddd_failed",
        "error": "Failed to parse JSON",
    }]
    assert captured_service_path["path"] == str(models_path.relative_to(tmp_path))
    assert captured_config["llm_service"] is service
    assert captured_config["prompts_path"] == "idos-config/prompts"
