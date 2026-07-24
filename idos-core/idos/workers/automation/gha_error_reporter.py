import os
import sys
import requests


REPO = os.environ.get("GITHUB_REPOSITORY", "")
API_BASE = f"https://api.github.com/repos/{REPO}" if REPO else ""


def create_issue(
    title: str,
    body: str,
    labels: list[str] | None = None,
    token: str = "",
) -> dict:
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    if not token:
        env_keys = [k for k in os.environ if "TOKEN" in k.upper() or "GH_" in k.upper()]
        raise RuntimeError(
            f"GITHUB_TOKEN or GH_TOKEN required. Available env vars with TOKEN/GH_: {env_keys}"
        )
    if not REPO:
        raise RuntimeError("GITHUB_REPOSITORY env var required")

    resp = requests.post(
        f"{API_BASE}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "title": title,
            "body": body,
            "labels": labels or ["auto-fix-proposed"],
        },
    )
    if resp.status_code == 403:
        detail = resp.json().get("message", "")
        raise RuntimeError(
            f"GitHub API 403 — missing 'issues: write' permission in workflow YAML. Detail: {detail}"
        )
    resp.raise_for_status()
    return resp.json()


class GHAErrorReporter:
    def __init__(self, token: str = ""):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")

    def report_failure(self, workflow: str = "", run_id: str = "", error_summary: str = "") -> dict:
        wf = workflow or os.environ.get("GITHUB_WORKFLOW", "unknown")
        rid = run_id or os.environ.get("GITHUB_RUN_ID", "0")
        err = error_summary or "Workflow failed (no detail provided)"
        run_url = f"https://github.com/{REPO}/actions/runs/{rid}" if REPO else f"(run #{rid})"

        title = f"[auto-fix] {wf} failed (run #{rid})"
        body = (
            f"## Workflow Failure\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| **Workflow** | `{wf}` |\n"
            f"| **Run** | [{rid}]({run_url}) |\n"
            f"| **Triggered by** | `{os.environ.get('GITHUB_EVENT_NAME', '?')}` |\n"
            f"| **Branch** | `{os.environ.get('GITHUB_REF_NAME', '?')}` |\n\n"
            f"### Error\n```\n{err}\n```\n"
        )
        return create_issue(title=title, body=body, token=self.token)


def main():
    reporter = GHAErrorReporter()
    wf = sys.argv[1] if len(sys.argv) > 1 else ""
    rid = sys.argv[2] if len(sys.argv) > 2 else ""
    err = sys.argv[3] if len(sys.argv) > 3 else ""
    issue = reporter.report_failure(workflow=wf, run_id=rid, error_summary=err)
    print(f"[AUTO-FIX] Issue created: {issue['html_url']}")


if __name__ == "__main__":
    main()
