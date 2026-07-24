import os
import re
import sys
import requests


REPO = os.environ.get("GITHUB_REPOSITORY", "")
API_BASE = f"https://api.github.com/repos/{REPO}" if REPO else ""


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _fetch_run_logs(run_id: str, token: str) -> str:
    try:
        resp = requests.get(
            f"{API_BASE}/actions/runs/{run_id}/logs",
            headers=_gh_headers(token),
        )
        if resp.status_code == 202:
            url = resp.json().get("url", "")
            if url:
                resp = requests.get(url, headers=_gh_headers(token))
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"(failed to fetch logs: {e})"


def _extract_error_snippet(logs: str) -> str:
    lines = logs.splitlines()
    error_lines = []
    capture = False
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(kw in lower for kw in ["traceback", "error:", "failed:", "runtimewarning", "exception"]):
            capture = True
        if capture:
            error_lines.append(line)
            if len(error_lines) >= 80:
                break
    return "\n".join(error_lines[-80:]) if error_lines else logs[:2000]


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

    @staticmethod
    def _fetch_error_from_run(run_id: str) -> str:
        if not REPO or not run_id or run_id == "0":
            return ""
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
        if not token:
            return ""
        try:
            jobs = requests.get(
                f"{API_BASE}/actions/runs/{run_id}/jobs",
                headers=_gh_headers(token),
            ).json()
            failed_steps = []
            for job in jobs.get("jobs", []):
                for step in job.get("steps", []):
                    if step.get("conclusion") == "failure":
                        failed_steps.append(f"[{job.get('name', '?')}] {step.get('name', '?')}")
            step_names = "; ".join(failed_steps) if failed_steps else ""
            logs = _fetch_run_logs(run_id, token)
            snippet = _extract_error_snippet(logs)
            if snippet:
                return f"Failed steps: {step_names}\n\n{snippet[:4000]}"
            return step_names or ""
        except Exception as e:
            return f"(auto-fetch error: {e})"

    def report_failure(self, workflow: str = "", run_id: str = "", error_summary: str = "") -> dict:
        wf = workflow or os.environ.get("GITHUB_WORKFLOW", "unknown")
        rid = run_id or os.environ.get("GITHUB_RUN_ID", "0")
        
        err = error_summary or os.environ.get("IDOS_ERROR_SUMMARY", "") or "Workflow failed (no detail provided)"
        
        auto_fetch = self._fetch_error_from_run(rid)
        err = err or auto_fetch or "Workflow failed (no detail provided)"
        
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
            f"### Error\n```\n{err}\n```\n\n"
            f"---\n"
            f"### To approve the fix\n"
            f"Comment `/idos-apply` on this issue to automatically create a PR with the proposed fix.\n"
        )
        return create_issue(title=title, body=body, token=self.token)


def _send_email_notification(issue: dict, workflow: str):
    try:
        from idos.workers.notifications.email_notifier import EmailNotifier
        n = EmailNotifier()
        run_url = f"https://github.com/{REPO}/actions/runs/{issue.get('run_id', '')}" if REPO else ""
        body = (
            f"Workflow: {workflow}\n"
            f"Run: {run_url}\n"
            f"Issue: {issue.get('html_url', '')}\n\n"
            f"Title: {issue.get('title', '')}\n"
            f"Description: An auto-fix issue was created automatically.\n"
            f"Review it and approve/apply the fix via GitHub Actions (Auto-Fix Agent)."
        )
        result = n.execute({
            "subject": f"[IDOS Auto-Fix] {workflow} failed",
            "body": body,
        })
        r = result.output if hasattr(result, "output") else result
        print(f"[EMAIL] Notification: {r.get('status', '?')}")
    except Exception as e:
        print(f"[EMAIL] Failed to send notification: {e}")


def _run_auto_analyze(issue_number: int):
    try:
        from idos.workers.automation.auto_fix_agent import AutoFixAgent
        agent = AutoFixAgent()
        result = agent.run({"action": "analyze", "issue_number": issue_number})
        status = "unknown"
        if isinstance(result, dict):
            status = result.get('status', '?')
            if 'status' in result:
                print(f"[AUTO-FIX] Analyze complete: {status} - PR: {result.get('pr_url', 'N/A')}")
            else:
                print(f"[AUTO-FIX] Analyze complete: {status}")
        elif hasattr(result, 'status'):
            status = result.status.value if hasattr(result.status, 'value') else str(result.status)
            print(f"[AUTO-FIX] Analyze complete: {status}")
        else:
            print(f"[AUTO-FIX] Analyze result: {result}")
    except Exception as e:
        print(f"[AUTO-FIX] Analyze failed (non-fatal): {e}")


def main():
    reporter = GHAErrorReporter()
    wf = sys.argv[1] if len(sys.argv) > 1 else ""
    rid = sys.argv[2] if len(sys.argv) > 2 else ""
    err = sys.argv[3] if len(sys.argv) > 3 else ""
    issue = reporter.report_failure(workflow=wf, run_id=rid, error_summary=err)
    issue["run_id"] = rid
    print(f"[AUTO-FIX] Issue created: {issue['html_url']}")
    _send_email_notification(issue, wf)
    issue_number = issue.get("number")
    if issue_number:
        _run_auto_analyze(issue_number)


if __name__ == "__main__":
    main()
