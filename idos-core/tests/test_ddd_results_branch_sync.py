import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.sync_ddd_results_branch import _sync_results_branch


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write(repo: Path, relative_path: str, content: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _init_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "remote", "add", "origin", str(remote))
    _write(repo, "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md", "base audit\n")
    _write(repo, ".github/workflows/ddd-pipeline.yml", "base workflow\n")
    _write(repo, "idos-core/tests/test_ddd_research_script.py", "base static test\n")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": []}\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial main")
    _git(repo, "push", "-u", "origin", "main")
    return repo, remote


def test_sync_resolves_main_owned_conflicts_and_preserves_queue(tmp_path, monkeypatch):
    repo, _ = _init_remote(tmp_path)
    owned_files = [
        "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md",
        ".github/workflows/ddd-pipeline.yml",
        "idos-core/tests/test_ddd_research_script.py",
    ]

    _git(repo, "switch", "-c", "codex/ddd-research-results")
    _write(repo, owned_files[0], "results audit\n")
    _write(repo, owned_files[1], "results workflow\n")
    _write(repo, owned_files[2], "results static test\n")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": ["AAPL"]}\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "persist scheduled results")
    _git(repo, "push", "-u", "origin", "codex/ddd-research-results")

    _git(repo, "switch", "main")
    main_contents = ["main audit\n", "main workflow\n", "main static test\n"]
    for path, content in zip(owned_files, main_contents):
        _write(repo, path, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "update canonical workflow and audit")
    _git(repo, "push", "origin", "main")

    monkeypatch.chdir(repo)
    _sync_results_branch()

    for path, expected in zip(owned_files, main_contents):
        assert (repo / path).read_text(encoding="utf-8") == expected
    queue = (repo / "cache/ddd_research_resume.json").read_text(encoding="utf-8")
    assert '"AAPL"' in queue
    assert _git(repo, "status", "--porcelain") == ""


def test_sync_aborts_data_conflicts_without_touching_persisted_state(tmp_path, monkeypatch):
    repo, _ = _init_remote(tmp_path)

    _git(repo, "switch", "-c", "codex/ddd-research-results")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": ["AAPL"]}\n')
    _git(repo, "add", "cache/ddd_research_resume.json")
    _git(repo, "commit", "-m", "persist AAPL")
    _git(repo, "push", "-u", "origin", "codex/ddd-research-results")

    _git(repo, "switch", "main")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": ["MSFT"]}\n')
    _git(repo, "add", "cache/ddd_research_resume.json")
    _git(repo, "commit", "-m", "update main queue")
    _git(repo, "push", "origin", "main")

    monkeypatch.chdir(repo)
    with pytest.raises(RuntimeError, match="unexpected results-branch merge conflicts: cache/ddd_research_resume.json"):
        _sync_results_branch()

    assert _git(repo, "status", "--porcelain") == ""
    assert (repo / "cache/ddd_research_resume.json").read_text(encoding="utf-8") == '{"pending": ["AAPL"]}\n'
