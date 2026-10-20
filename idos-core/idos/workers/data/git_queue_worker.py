import subprocess
from pathlib import Path
from typing import Any

from idos.data.sqlite import SQLiteStore
from idos.workers.base import BaseWorker


class GitQueueWorker(BaseWorker):
    name = "git_queue"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.store = SQLiteStore(config.get("db_path", "idos.db"))
        self.repo_path = config.get("repo_path", ".")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        pending = self.store.get_pending_commits(limit=context.get("limit", 10))
        if not pending:
            return {"commits_processed": 0, "message": "No pending commits"}

        committed: list[str] = []
        errors: list[str] = []

        for commit in pending:
            try:
                file_path = Path(self.repo_path) / commit["file_path"]
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(commit["content"], encoding="utf-8")

                result = subprocess.run(
                    ["git", "add", str(file_path)],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    errors.append(f"git add failed for {commit['file_path']}: {result.stderr}")
                    continue

                result = subprocess.run(
                    [
                        "git", "commit", "-m",
                        f"IDOS auto: {commit.get('file_path', 'update')}",
                        "--author", "IDOS Bot <idos@familyoffice.com>",
                    ],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0 and "nothing to commit" not in result.stderr:
                    errors.append(f"git commit failed: {result.stderr}")

                self.store.mark_commit_done(commit["id"])
                committed.append(commit["file_path"])
            except Exception as e:
                errors.append(f"Error processing {commit.get('file_path', 'unknown')}: {str(e)}")

        return {
            "commits_processed": len(committed),
            "committed_files": committed,
            "errors": errors,
        }
