#!/usr/bin/env python3
"""
Test script for IDOS Auto-Fix workflow

This script simulates the GitHub Actions environment for testing purposes.
It requires GitHub API tokens and proper environment variables to work.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def setup_test_environment():
    """Set up a mock GitHub Actions environment for testing"""
    # Create a temporary directory for the test
    test_dir = tempfile.mkdtemp(prefix="idos_test_")
    print(f"Test directory: {test_dir}")
    
    # Change to the test directory
    os.chdir(test_dir)
    
    # Create basic project structure
    os.makedirs("idos-core/idos/workers/automation")
    
    # Create a minimal version of gha_error_reporter.py for testing
    reporter_code = '''
import os
import re
import sys
import requests

REPO = os.environ.get("GITHUB_REPOSITORY", "")
API_BASE = f"https://api.github.com/repos/{REPO}" if REPO else ""

class MockGitHubAPI:
    def __init__(self, token):
        self.token = token
        self.issues = {}
        self.issues_next_id = 1
        
    def create_issue(self, title, body, labels=None):
        issue = {
            "number": self.issues_next_id,
            "title": title,
            "body": body,
            "labels": labels or ["auto-fix-proposed"],
            "html_url": f"https://github.com/{REPO}/issues/{self.issues_next_id}"
        }
        self.issues[self.issues_next_id] = issue
        self.issues_next_id += 1
        return issue
        
    def get_issue(self, issue_number):
        return self.issues.get(issue_number)
        
    def add_comment(self, issue_number, body):
        issue = self.issues.get(issue_number)
        if issue:
            if "comments" not in issue:
                issue["comments"] = []
            comment = {
                "id": len(issue["comments"]) + 1,
                "body": body
            }
            issue["comments"].append(comment)
            return comment
        return None
        
    def update_issue(self, issue_number, **kwargs):
        issue = self.issues.get(issue_number)
        if issue:
            issue.update(kwargs)
            return issue
        return None

# Global GitHub client
token = os.environ.get("GITHUB_TOKEN", "test-token")
gh_client = MockGitHubAPI(token)
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

    return gh_client.create_issue(title, body, labels)

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
            f"## Workflow Failure\\n\\n"
            f"| Field | Value |\\n"
            f"|-------|-------|\\n"
            f"| **Workflow** | `{wf}` |\\n"
            f"| **Run** | [{rid}]({run_url}) |\\n"
            f"| **Triggered by** | `{os.environ.get('GITHUB_EVENT_NAME', '?')}` |\\n"
            f"| **Branch** | `{os.environ.get('GITHUB_REF_NAME', '?')}` |\\n\\n"
            f"### Error\\n```\\n{err}\\n```\\n\\n"
            f"---\\n"
            f"### To approve the fix\\n"
            f"Comment `/idos-apply` on this issue to automatically create a PR with the proposed fix.\\n"
        )
        return create_issue(title=title, body=body, token=self.token)

class MockAutoFixAgent:
    def __init__(self, config=None):
        self.config = config or {}
        self.issues = gh_client.issues
        
    def run(self, context):
        action = context.get("action", "analyze")
        issue_number = context.get("issue_number", 0)
        
        if action == "analyze":
            return self._analyze(issue_number)
        elif action == "apply":
            return self._apply(issue_number)
        else:
            raise ValueError(f"Unknown action: {action}")
            
    def _analyze(self, issue_number):
        issue = self.issues.get(issue_number)
        if not issue:
            return {"status": "failed", "error": f"Issue #{issue_number} not found"}
            
        body = issue.get("body", "")
        
        # Look for run ID in the issue body
        run_id = None
        for line in body.splitlines():
            m = re.search(r"\\| \\*\\*Run\\*\\* \\? \\[\\((\\d+)\\)\]", line)
            if m:
                run_id = m.group(1)
                break
                
        error_summary = f"Simulated workflow failure for run {run_id}" if run_id else "Workflow failed"
        error_log = f"(Mock log for run {run_id})\\n\\nError: Mock error in test run"
        
        # Generate a realistic fix plan
        fix_plan = {
            "summary": "Fix simulated workflow failure in CI/CD pipeline",
            "root_cause": "Mock error in workflow configuration",
            "files": [
                {
                    "path": "idos-core/.github/workflows/ci.yml",
                    "action": "modify", 
                    "description": "Add proper permissions and error handling",
                    "diff_or_content": "changed:\n- id: Test workflow fix\n  run: echo 'fix applied'\n  # Added error handling"
                },
                {
                    "path": "idos-core/idos/workers/automation/gha_error_reporter.py",
                    "action": "modify",
                    "description": "Improve error reporting with more detail",
                    "diff_or_content": "changed:\n+ Add more detailed error information\n+ Improve logging"
                }
            ],
            "test_command": "python -m pytest idos-core/tests/ -v"
        }
        
        # Post the fix plan as a comment
        plan_md = self._format_plan_markdown(fix_plan)
        self.issues[issue_number]["comments"] = self.issues[issue_number].get("comments", [])
        self.issues[issue_number]["comments"].append({
            "body": plan_md
        })
        
        # Update issue labels
        self.issues[issue_number]["labels"] = ["auto-fix-analyzed"]
        
        return {"status": "analyzed", "issue_number": issue_number, "fix_plan": fix_plan}
        
    def _apply(self, issue_number):
        issue = self.issues.get(issue_number)
        if not issue:
            return {"status": "failed", "error": f"Issue #{issue_number} not found"}
            
        # Get the fix plan
        fix_plan = issue.get("fix_plan")
        if not fix_plan:
            return {"status": "failed", "error": "No fix plan found"}
            
        # In a real implementation, this would create a PR
        # For testing, we'll just return the plan
        return {
            "status": "pr_created",
            "issue_number": issue_number,
            "pr_number": issue.get("number", 999),
            "pr_url": f"https://github.com/{REPO}/pull/{issue.get('number', 999)}",
            "branch": "auto-fix/issue-{issue_number}"
        }
        
    def _format_plan_markdown(self, plan):
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
        lines.append("idos auto-fix apply {issue_number}")
        lines.append("```")
        lines.append("")
        lines.append("Or trigger via GitHub Actions: workflow_dispatch with action=apply")
        return "\\n".join(lines)

def main():
    print("=== IDOS Auto-Fix Workflow Test ===")
    
    # Set up test environment
    os.environ["GITHUB_REPOSITORY"] = "testuser/test-repo"
    os.environ["GITHUB_TOKEN"] = "test-token"
    os.environ["GITHUB_WORKFLOW"] = "test-workflow"
    os.environ["GITHUB_RUN_ID"] = "12345"
    os.environ["GITHUB_EVENT_NAME"] = "push"
    os.environ["GITHUB_REF_NAME"] = "main"
    
    # Test GHAErrorReporter
    print("\\n1. Testing GHAErrorReporter...")
    reporter = GHAErrorReporter()
    
    # Report a failure
    issue = reporter.report_failure(
        workflow="CI/CD Pipeline",
        run_id="12345",
        error_summary="Mock error: Something went wrong in the workflow"
    )
    
    print(f"   Issue created: #{issue['number']}")
    print(f"   Title: {issue['title']}")
    print(f"   URL: {issue['html_url']}")
    
    # Test AutoFixAgent
    print("\\n2. Testing AutoFixAgent.analyze()...")
    agent = MockAutoFixAgent()
    
    result = agent.run({
        'action': 'analyze',
        'issue_number': issue['number']
    })
    
    print(f"   Status: {result['status']}")
    print(f"   Issue number: {result.get('issue_number')}")
    
    if result['status'] == 'analyzed':
        print(f"   Fix plan generated with {len(result.get('fix_plan', {}).get('files', []))} file changes")
        
        # Check if the fix plan was saved in the issue
        saved_issue = gh_client.get_issue(issue['number'])
        if saved_issue:
            print(f"   Issue comments: {len(saved_issue.get('comments', []))}")
            print(f"   Issue labels: {saved_issue.get('labels', [])}")
    
    print("\\n=== Test completed successfully! ===")
    print(f"To view the test results, check issue #{issue['number']} at {issue['html_url']}")
    print("The issue should have a comment with the auto-fix plan")

if __name__ == "__main__":
    main()
