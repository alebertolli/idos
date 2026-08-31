from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class PipelineMetrics:
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0

    finviz_count: int = 0
    finviz_from_cache: bool = False
    finviz_tickers: list[str] = field(default_factory=list)

    operable_count: int = 0
    operable_filtered: int = 0

    pre_score_count: int = 0
    pre_score_rejected: int = 0

    fetch_new: int = 0
    fetch_cached: int = 0
    fetch_errors: list[dict] = field(default_factory=list)

    scout_passed: int = 0
    scout_rejected: int = 0
    new_watchlist: list[dict] = field(default_factory=list)

    opportunities_created: int = 0
    opportunities_eligible: int = 0
    opportunities_existing: int = 0

    downgraded_to_watchlist: int = 0
    upgraded_to_screened: int = 0

    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "finviz_count": self.finviz_count,
            "finviz_from_cache": self.finviz_from_cache,
            "operable_count": self.operable_count,
            "operable_filtered": self.operable_filtered,
            "pre_score_count": self.pre_score_count,
            "fetch_new": self.fetch_new,
            "fetch_cached": self.fetch_cached,
            "fetch_errors": len(self.fetch_errors),
            "scout_passed": self.scout_passed,
            "scout_rejected": self.scout_rejected,
            "new_watchlist_count": len(self.new_watchlist),
            "opportunities_eligible": self.opportunities_eligible,
            "opportunities_existing": self.opportunities_existing,
            "opportunities_created": self.opportunities_created,
            "downgraded_to_watchlist": self.downgraded_to_watchlist,
            "upgraded_to_screened": self.upgraded_to_screened,
            "errors": self.errors,
        }

class PipelineReportGenerator:
    def generate(self, metrics: PipelineMetrics) -> str:
        lines = []
        lines.append("IDOS Monthly Universe Pipeline")
        lines.append(f"{metrics.finished_at[:10]} | Duration: {metrics.duration_seconds:.0f}s")
        lines.append("")

        lines.append("Pipeline Results:")
        lines.append(f"  Finviz Screening: {metrics.finviz_count} tickers" +
                     (" (cached)" if metrics.finviz_from_cache else ""))
        lines.append(f"  Operable Filter: {metrics.operable_count} tickers" +
                     (f" ({metrics.operable_filtered} filtered out)" if metrics.operable_filtered else ""))
        if metrics.pre_score_count > 0:
            lines.append(f"  Pre-Score: {metrics.pre_score_count} tickers" +
                         (f" ({metrics.pre_score_rejected} rejected)" if metrics.pre_score_rejected else ""))
        lines.append(f"  Data Fetch: {metrics.fetch_new} new, {metrics.fetch_cached} cached")
        lines.append(f"  Scout: {metrics.scout_passed} passed, {metrics.scout_rejected} rejected")
        lines.append("")

        if metrics.new_watchlist:
            lines.append(f"New Watchlist Additions ({len(metrics.new_watchlist)}):")
            for entry in metrics.new_watchlist[:10]:
                score = entry.get("score", "N/A")
                rank = entry.get("rank", "N/A")
                lines.append(f"  {entry['ticker']:<8} score: {score} | rank: {rank}")
            if len(metrics.new_watchlist) > 10:
                lines.append(f"  ... and {len(metrics.new_watchlist) - 10} more")
            lines.append("")

        if metrics.opportunities_eligible:
            lines.append(f"  Opportunities: {metrics.opportunities_created} created, "
                         f"{metrics.opportunities_existing} already exist, "
                         f"{metrics.opportunities_eligible} eligible")
            lines.append("")

        if metrics.fetch_errors:
            for err in metrics.fetch_errors[:5]:
                lines.append(f"  {err.get('ticker', '?')} — {err.get('error', 'unknown')}")
            lines.append("")

        if metrics.errors:
            lines.append(f"Errors ({len(metrics.errors)}):")
            for err in metrics.errors[:5]:
                step = err.get("step", "?")
                msg = err.get("error", "unknown")
                lines.append(f"  [{step}] {msg}")
            lines.append("")

        lines.append(f"Report generated: {metrics.finished_at}")

        return "\n".join(lines)

    def save(self, report: str, journal_path: str, filename: str = ""):
        if not filename:
            filename = f"universe-{datetime.now(AR_TZ).strftime('%Y-%m-%d')}.md"
        reports_dir = Path(journal_path) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / filename
        report_path.write_text(report, encoding="utf-8")
        return str(report_path)