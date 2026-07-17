from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class ReportType(StrEnum):
    DUE_DILIGENCE = "due_diligence"
    WIKI = "wiki"
    WEEKLY = "weekly"
    DECISION = "decision"


@dataclass
class ReportSection:
    title: str
    content: str
    level: int = 1


@dataclass
class Report:
    report_type: ReportType
    title: str
    ticker: str
    sections: list[ReportSection] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()


class ReportGenerator:
    def generate_dd_report(self, ticker: str, ddd_result: dict[str, Any]) -> Report:
        sections = [
            ReportSection("Executive Summary", ddd_result.get("executive_summary", ""), 1),
            ReportSection("Business Analysis", ddd_result.get("business_analysis", ""), 1),
            ReportSection("Financial Analysis", ddd_result.get("financial_analysis", ""), 1),
            ReportSection("Management Assessment", ddd_result.get("management_assessment", ""), 1),
            ReportSection("Risk Factors", ddd_result.get("risk_factors", ""), 1),
            ReportSection("Valuation", ddd_result.get("valuation", ""), 1),
            ReportSection("Recommendation", ddd_result.get("recommendation", ""), 1),
        ]
        return Report(ReportType.DUE_DILIGENCE, f"Due Diligence: {ticker}", ticker, sections)

    def generate_wiki_report(self, ticker: str, wiki_data: dict[str, Any]) -> Report:
        sections = []
        for key, value in wiki_data.items():
            sections.append(ReportSection(key.replace("_", " ").title(), str(value)))
        return Report(ReportType.WIKI, f"Wiki: {ticker}", ticker, sections)

    def generate_weekly_report(self, positions: list[dict[str, Any]],
                                metrics: dict[str, Any]) -> Report:
        sections = [
            ReportSection("Portfolio Summary", f"Total positions: {len(positions)}", 1),
            ReportSection("Performance", str(metrics.get("performance", {}))),
            ReportSection("Risk Metrics", str(metrics.get("risk", {}))),
            ReportSection("Actions Taken", str(metrics.get("actions", []))),
        ]
        return Report(ReportType.WEEKLY, f"Weekly Report: {metrics.get('week', 'N/A')}", "", sections)

    def generate_decision_report(self, ticker: str, decision_data: dict[str, Any]) -> Report:
        sections = [
            ReportSection("Decision Summary", decision_data.get("summary", ""), 1),
            ReportSection("Conviction Analysis", str(decision_data.get("conviction", {}))),
            ReportSection("Assessment Results", str(decision_data.get("assessments", {}))),
            ReportSection("Final Verdict", decision_data.get("verdict", ""), 1),
        ]
        return Report(ReportType.DECISION, f"Decision: {ticker}", ticker, sections)

    def render_markdown(self, report: Report) -> str:
        lines = [f"# {report.title}", f"*Generated: {report.generated_at}*", ""]
        for section in report.sections:
            prefix = "#" * section.level
            lines.append(f"{prefix} {section.title}")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines)
