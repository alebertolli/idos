import json
import os
import re
import requests
import sys
import time
from pathlib import Path
from typing import Any

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


REPO = os.environ.get("GITHUB_REPOSITORY", "")
API_BASE = f"https://api.github.com/repos/{REPO}" if REPO else ""


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")


def _gh_get(path: str, token: str) -> Any:
    if not API_BASE:
        raise RuntimeError(f"GITHUB_REPOSITORY not set (API_BASE empty) - cannot fetch {path}")
    resp = requests.get(f"{API_BASE}/{path}", headers=_gh_headers(token))
    resp.raise_for_status()
    return resp.json()


def _gh_post(path: str, data: dict, token: str) -> Any:
    resp = requests.post(f"{API_BASE}/{path}", headers=_gh_headers(token), json=data)
    if resp.status_code == 403:
        raise RuntimeError(
            f"GitHub API 403 on POST {path}: {resp.json().get('message', '')}"
        )
    resp.raise_for_status()
    return resp.json()


def _gh_patch(path: str, data: dict, token: str) -> Any:
    resp = requests.patch(f"{API_BASE}/{path}", headers=_gh_headers(token), json=data)
    resp.raise_for_status()
    return resp.json()


def _gh_put(path: str, data: dict, token: str) -> Any:
    resp = requests.put(f"{API_BASE}/{path}", headers=_gh_headers(token), json=data)
    resp.raise_for_status()
    return resp.json()


def _fetch_run_logs(run_id: str, token: str) -> str:
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


def _fetch_run_jobs(run_id: str, token: str) -> list[dict]:
    data = _gh_get(f"actions/runs/{run_id}/jobs", token)
    return data.get("jobs", [])


def _get_llm_client():
    try:
        from idos.ai.llm import LLMClient
        return LLMClient()
    except Exception:
        pass
    try:
        provider = os.environ.get("IDOS_LLM_PROVIDER", "openrouter")
        model = os.environ.get("IDOS_LLM_MODEL", "openai/gpt-4o")
        api_key = (
            os.environ.get("IDOS_LLM_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        if not api_key:
            return None
        from idos.ai.llm import LLMClient
        return LLMClient(provider=provider, model=model, api_key=api_key)
    except Exception:
        return None


_FIX_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "root_cause": {"type": "string"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "action": {"type": "string", "enum": ["modify", "create", "delete"]},
                    "description": {"type": "string"},
                    "diff_or_content": {"type": "string"},
                },
                "required": ["path", "action", "description"],
            },
        },
        "test_command": {"type": "string"},
    },
    "required": ["summary", "root_cause", "files"],
}


class AutoFixAgent(BaseWorker):
    name = "auto_fix"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.token = _get_token()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        action = context.get("action", "analyze")
        issue_number = context.get("issue_number", 0)

        if action == "analyze":
            return self._analyze(issue_number)
        elif action == "apply":
            return self._apply(issue_number)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _analyze(self, issue_number: int) -> dict[str, Any]:
        issue = _gh_get(f"issues/{issue_number}", self.token)
        body = issue.get("body", "")

        run_id = None
        for line in body.splitlines():
            m = re.search(r"\| \*\*Run\*\* \| \[(\d+)\]", line)
            if m:
                run_id = m.group(1)
                break

        error_log = ""
        error_summary = ""
        if run_id:
            try:
                jobs = _fetch_run_jobs(run_id, self.token)
                for job in jobs:
                    for step in job.get("steps", []):
                        if step.get("conclusion") == "failure":
                            error_summary = step.get("name", "?")
                            break
                raw_logs = _fetch_run_logs(run_id, self.token)
                error_log = self._extract_error_snippet(raw_logs)
            except Exception as e:
                error_log = f"(failed to fetch logs for run {run_id}: {e})"

        fix_plan = self._generate_fix_plan(body, error_log, error_summary, issue_number)

        plan_md = self._format_plan_markdown(fix_plan)
        _gh_post(
            f"issues/{issue_number}/comments",
            {"body": plan_md},
            self.token,
        )
        _gh_patch(
            f"issues/{issue_number}",
            {"labels": ["auto-fix-analyzed"]},
            self.token,
        )
        return {"status": "analyzed", "issue_number": issue_number, "fix_plan": fix_plan}

    def _apply(self, issue_number: int) -> dict[str, Any]:
        comments = _gh_get(f"issues/{issue_number}/comments", self.token)
        plan = None
        for comment in reversed(comments):
            cbody = comment.get("body", "")
            if "## 🔧 Auto-Fix Plan" in cbody:
                plan = self._parse_plan_from_markdown(cbody)
                break

        if not plan:
            raise RuntimeError(f"No fix plan found in issue #{issue_number} comments")

        branch = f"auto-fix/issue-{issue_number}"
        self._ensure_branch(branch)

        for file_change in plan.get("files", []):
            self._apply_file_change(branch, file_change)

        pr = _gh_post(
            "pulls",
            {
                "title": f"[auto-fix] {plan.get('summary', 'Fix')}",
                "body": (
                    f"## Auto-Fix Proposal\n\n"
                    f"Closes #{issue_number}\n\n"
                    f"### Root cause\n{plan.get('root_cause', '')}\n\n"
                    f"### Changes\n"
                    + "\n".join(
                        f"- **{f['action']}** `{f['path']}`: {f['description']}"
                        for f in plan.get("files", [])
                    )
                ),
                "head": branch,
                "base": "main",
            },
            self.token,
        )

        _gh_post(
            f"issues/{issue_number}/comments",
            {"body": f"✅ PR created: [#{pr['number']}]({pr['html_url']})"},
            self.token,
        )
        _gh_patch(
            f"issues/{issue_number}",
            {"labels": ["auto-fix-pr-ready"]},
            self.token,
        )
        return {
            "status": "pr_created",
            "issue_number": issue_number,
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "branch": branch,
        }

    def _generate_fix_plan(
        self, issue_body: str, error_log: str, error_step: str, issue_number: int
    ) -> dict[str, Any]:
        llm = _get_llm_client()
        if not llm:
            return self._fallback_plan(issue_body, error_log, error_step)

        prompt = (
            "Eres un ingeniero de software experto en Python y GitHub Actions. "
            "Analiza este error de CI y genera un plan de fix.\n\n"
            f"### Issue Body\n{issue_body}\n\n"
            f"### Failing Step\n{error_step}\n\n"
            f"### Error Log Snippet\n{error_log[:8000]}\n\n"
            "Genera un plan JSON con: summary, root_cause, files (path, action, description, diff_or_content), test_command."
        )
        try:
            result = llm.generate_structured(
                prompt=prompt,
                system_prompt="You are a senior DevOps/Python engineer. Output ONLY valid JSON matching the schema.",
                temperature=0.1,
            )
            plan = result if isinstance(result, dict) else json.loads(str(result))
        except Exception as e:
            return self._fallback_plan(issue_body, error_log, error_step, fallback_reason=str(e))

        base_path = Path.cwd()
        for fch in plan.get("files", []):
            path = fch.get("path", "")
            full = base_path / path
            if fch.get("action") in ("modify",) and not full.exists():
                fch["action"] = "create"
            if fch.get("action") in ("modify", "create") and full.exists():
                current = full.read_text(encoding="utf-8", errors="replace")
                fch.setdefault("current_content", current)
        return plan

    def _fallback_plan(
        self, issue_body: str, error_log: str, error_step: str, fallback_reason: str = ""
    ) -> dict[str, Any]:
        files = []
        error_lines = error_log.splitlines() if error_log else []
        for line in error_lines:
            m = re.search(r'File "([^"]+)"', line)
            if m:
                path = m.group(1)
                try:
                    rel = Path(path).relative_to(Path.cwd())
                except ValueError:
                    rel = Path(path)
                if str(rel) not in [f.get("path") for f in files]:
                    files.append({"path": str(rel), "action": "modify", "description": "Review this file"})

        return {
            "summary": f"Auto-fix for {error_step or 'workflow failure'}",
            "root_cause": error_log[:2000] if error_log else issue_body[:1000],
            "files": files or [{"path": "unknown", "action": "modify", "description": "Review manually"}],
            "test_command": "python -m pytest idos-core/tests/ -v",
        }

    def _format_plan_markdown(self, plan: dict[str, Any]) -> str:
        lines = [
            "## 🔧 Auto-Fix Plan",
            "",
            f"**Summary:** {plan.get('summary', 'N/A')}",
            "",
            f"**Root cause:** {plan.get('root_cause', 'N/A')}",
            "",
            "### Files to change",
            "",
        ]
        for fch in plan.get("files", []):
            lines.append(f"- **{fch['action']}** `{fch['path']}`: {fch['description']}")
        lines.append("")
        lines.append("### To apply")
        lines.append("")
        lines.append("Run the following command to review and apply this fix:")
        lines.append("")
        lines.append("```bash")
        lines.append(f"idos auto-fix apply {plan.get('_issue_number', '')}")
        lines.append("```")
        lines.append("")
        lines.append("Or trigger via GitHub Actions: `workflow_dispatch` with action=apply")
        return "\n".join(lines)

    def _parse_plan_from_markdown(self, md: str) -> dict[str, Any]:
        plan: dict[str, Any] = {"files": []}
        for line in md.splitlines():
            m = re.match(r"\*\*Summary:\*\*\s*(.+)", line)
            if m:
                plan["summary"] = m.group(1).strip()
            m = re.match(r"\*\*Root cause:\*\*\s*(.+)", line)
            if m:
                plan["root_cause"] = m.group(1).strip()
            m = re.match(r"- \*\*(modify|create|delete)\*\*\s+`(.+?)`:\s*(.+)", line)
            if m:
                plan["files"].append({
                    "action": m.group(1),
                    "path": m.group(2),
                    "description": m.group(3).strip(),
                })
        return plan

    def _ensure_branch(self, branch: str):
        try:
            _gh_get(f"git/ref/heads/{branch}", self.token)
            return
        except Exception:
            pass
        main_ref = _gh_get("git/ref/heads/main", self.token)
        _gh_post("git/refs", {"ref": f"refs/heads/{branch}", "sha": main_ref["object"]["sha"]}, self.token)

    def _apply_file_change(self, branch: str, change: dict):
        path = change["path"]
        action = change.get("action", "modify")

        if action == "delete":
            try:
                current = _gh_get(f"contents/{path}?ref={branch}", self.token)
                _gh_put(
                    f"contents/{path}",
                    {"message": f"auto-fix: delete {path}", "sha": current["sha"], "branch": branch},
                    self.token,
                )
            except Exception:
                pass
            return

        content = change.get("diff_or_content", "")
        if not content and action == "modify":
            try:
                current = _gh_get(f"contents/{path}?ref={branch}", self.token)
                import base64
                old = base64.b64decode(current["content"]).decode("utf-8")
                content = old
            except Exception:
                content = ""
        if not content:
            content = f"# auto-fix placeholder for {path}\n"

        import base64
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        try:
            current = _gh_get(f"contents/{path}?ref={branch}", self.token)
            _gh_put(
                f"contents/{path}",
                {"message": f"auto-fix: {action} {path}", "content": encoded, "sha": current["sha"], "branch": branch},
                self.token,
            )
        except Exception:
            _gh_put(
                f"contents/{path}",
                {"message": f"auto-fix: {action} {path}", "content": encoded, "branch": branch},
                self.token,
            )

    @staticmethod
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
