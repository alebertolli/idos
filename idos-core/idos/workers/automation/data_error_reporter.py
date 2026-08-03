import os
from datetime import datetime
from pathlib import Path

from idos.resilience.error_manager import ErrorManager
from idos.workers.automation.gha_error_reporter import create_issue

SEVERITY_ORDER = {"alta": 3, "media": 2, "baja": 1}


def consolidate_errors(base_path: str | Path | None = None) -> list[dict]:
    """Read today's unreported errors from the ErrorManager store."""
    em = ErrorManager(base_path)
    errors = em.errors_since(days=1)
    errors = [e for e in errors if not e.reported]
    return [e.to_dict() for e in errors]


def build_issue_body(errors: list[dict], run_url: str = "") -> str:
    lines = [
        "## Errores de Datos Detectados",
        "",
        "El proceso de Error Management (SDD-16 §17.2) detectó errores de datos en el pipeline diario.",
        "",
        "| Ticker | Severidad | Categoría | Mensaje |",
        "|--------|-----------|-----------|---------|",
    ]
    for e in sorted(errors, key=lambda x: (-SEVERITY_ORDER.get(x.get("severity", "media"), 2), x.get("ticker", ""))):
        ticker = e.get("ticker") or "SISTEMA"
        lines.append(
            f"| {ticker} | {e.get('severity', '?')} | {e.get('category', '?')} | {e.get('message', '?')} |"
        )
    lines.append("")
    if run_url:
        lines.append(f"**Run:** {run_url}")
    lines.append("")
    lines.append("**Acción:** Revisar la causa raíz (fuente de datos, configuración o Buy List) y corregir.")
    return "\n".join(lines)


def report_data_errors(base_path: str | Path | None = None, mark_reported: bool = True) -> dict:
    """Create/update ONE consolidated GitHub issue per day for data errors."""
    em = ErrorManager(base_path)
    errors = [e for e in em.errors_since(days=1) if not e.reported]
    if not errors:
        return {"status": "no_errors", "issues_created": 0, "errors": []}

    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    run_url = ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"⚠️ IDOS: errores de datos [{today}]"
    body = build_issue_body(errors, run_url)

    labels = ["auto-fix-proposed"]
    try:
        issue = create_issue(title=title, body=body, labels=labels)
    except Exception as e:
        print(f"[ERROR-REPORT] No se pudo crear el issue: {e}")
        return {"status": "failed", "error": str(e), "errors": errors}

    if mark_reported:
        em.mark_reported(today)

    print(f"[ERROR-REPORT] Issue creado: {issue.get('html_url', '?')}")
    return {
        "status": "issue_created",
        "issue_url": issue.get("html_url", ""),
        "errors": errors,
        "issues_created": 1,
    }


if __name__ == "__main__":
    result = report_data_errors()
    print(f"Status: {result.get('status')} | Errores: {len(result.get('errors', []))}")
