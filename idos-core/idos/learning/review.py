"""Private post-mortem review; no strategy parameter is changed here."""

from datetime import datetime
from pathlib import Path
import re

import yaml

from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.timezone import AR_TZ


def _report_path(base_path: Path, pm_id: str) -> Path:
    if not re.fullmatch(r"pm-[0-9a-f]{8}", pm_id):
        raise ValueError("Invalid post-mortem ID")
    return base_path / "private-data" / "learning" / "post_mortems" / f"{pm_id}.yml"


def list_reports(base_path: Path) -> list[dict]:
    directory = base_path / "private-data" / "learning" / "post_mortems"
    reports = []
    for path in sorted(directory.glob("pm-*.yml")):
        report = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(report, dict):
            reports.append(report)
    return reports


def approve_report(base_path: Path, pm_id: str, reviewer: str) -> dict:
    """Approve the report and archive its opportunity, leaving proposals unapplied."""
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    path = _report_path(base_path, pm_id)
    if not path.is_file():
        raise FileNotFoundError(pm_id)
    report = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("id") != pm_id:
        raise ValueError("Invalid post-mortem record")

    sqlite = SQLiteStore(base_path / "idos.db")
    opp_id = report.get("opp_id")
    opp = sqlite.get_opportunity(opp_id)
    if not opp or opp.get("ticker") != report.get("ticker"):
        raise ValueError("Post-mortem opportunity mismatch")
    if report.get("review_status") == "APPROVED" and opp["status"] == "ARCHIVED":
        return report
    if opp["status"] != OpportunityStatus.POST_MORTEM.value:
        raise ValueError("Opportunity is not awaiting post-mortem review")
    if report.get("review_status") not in ("PENDING_REVIEW", "APPROVED"):
        raise ValueError("Post-mortem is not awaiting review")

    report["review_status"] = "APPROVED"
    report.setdefault("approved_by", reviewer.strip())
    report.setdefault("approved_at", datetime.now(AR_TZ).isoformat())
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

    opp["status"] = OpportunityStatus.ARCHIVED.value
    opp["updated_at"] = datetime.now(AR_TZ).isoformat()
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, "POST_MORTEM", "ARCHIVED",
                             cause=f"post_mortem_approved_by:{report['approved_by']}",
                             worker="learning_review")
    sqlite.log_event("post_mortem:approved", {
        "opp_id": opp_id, "pm_id": pm_id, "reviewer": report["approved_by"],
    })
    return report
