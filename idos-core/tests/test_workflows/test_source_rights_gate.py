from pathlib import Path

import yaml


RIGHTS_GATE = "vars.IDOS_DATA_RIGHTS_CONFIRMED == 'true'"
PAGES_SUCCESS_GATE = (
    "github.event_name != 'workflow_run' || "
    "github.event.workflow_run.conclusion == 'success'"
)
WORKFLOW_JOBS = {
    ".github/workflows/monthly-universe-pipeline.yml": "pipeline",
    ".github/workflows/daily-refresh.yml": "refresh",
    ".github/workflows/ddd-pipeline.yml": "ddd",
    ".github/workflows/gh-pages.yml": "build",
}


def test_data_and_publication_jobs_require_explicit_source_rights_confirmation():
    repository_root = Path(__file__).resolve().parents[3]

    for relative_path, job_name in WORKFLOW_JOBS.items():
        workflow = yaml.load(
            (repository_root / relative_path).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

        job_condition = workflow["jobs"][job_name]["if"]
        assert RIGHTS_GATE in job_condition
        if relative_path == ".github/workflows/gh-pages.yml":
            assert PAGES_SUCCESS_GATE in job_condition
        else:
            assert job_condition == RIGHTS_GATE


def test_source_rights_guard_does_not_disable_workflow_definitions():
    repository_root = Path(__file__).resolve().parents[3]

    for relative_path in WORKFLOW_JOBS:
        workflow = yaml.load(
            (repository_root / relative_path).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

        assert "on" in workflow
