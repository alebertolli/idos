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
    _write(repo, "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md", "# DDD audit\n\nBase entry\n")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": []}\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial main")
    _git(repo, "push", "-u", "origin", "main")
    return repo, remote


def test_sync_resolves_only_main_owned_audit_conflict_and_preserves_queue(tmp_path, monkeypatch):
    repo, _ = _init_remote(tmp_path)

    _git(repo, "switch", "-c", "codex/ddd-research-results")
    _write(repo, "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md", "# DDD audit\n\nResults branch entry\n")
    _write(repo, "cache/ddd_research_resume.json", '{"pending": ["AAPL"]}\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "persist scheduled results")
    _git(repo, "push", "-u", "origin", "codex/ddd-research-results")

    _git(repo, "switch", "main")
    _write(repo, "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md", "# DDD audit\n\nMain audit entry\n")
    _git(repo, "add", "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md")
    _git(repo, "commit", "-m", "update main audit")
    _git(repo, "push", "origin", "main")

    monkeypatch.chdir(repo)
    _sync_results_branch()

    audit = (repo / "SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md").read_text(encoding="utf-8")
    queue = (repo / "cache/ddd_research_resume.json").read_text(encoding="utf-8")
    assert "Main audit entry" in audit
    assert "Results branch entry" not in audit
    assert '"AAPL"' in queue
    assert _git(repo, "status", "--porcelain") == ""


def test_sync_aborts_unexpected_conflicts_without_touching_persisted_state(tmp_path, monkeypatch):
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

