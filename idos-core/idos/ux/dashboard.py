from dataclasses import dataclass, field
from typing import Any


@dataclass
class DashboardSummary:
    total_opportunities: int = 0
    active_positions: int = 0
    watchlist_count: int = 0
    total_capital: float = 0.0
    cash_balance: float = 0.0
    cash_pct: float = 0.0
    best_conviction: int = 0
    worst_conviction: int = 0
    recent_decisions: int = 0
    pending_decisions: int = 0
    risk_alerts: int = 0


class DashboardAPI:
    def build_summary(self, opportunities: list[dict[str, Any]],
                      positions: list[dict[str, Any]] | None = None,
                      watchlist: list[dict[str, Any]] | None = None,
                      decisions: list[dict[str, Any]] | None = None,
                      risk_alerts: list[dict[str, Any]] | None = None,
                      cash: dict[str, Any] | None = None) -> DashboardSummary:

        positions = positions or []
        watchlist = watchlist or []
        decisions = decisions or []
        risk_alerts = risk_alerts or []
        cash = cash or {}

        convictions = [p.get("conviction", 0) for p in positions]
        pending = [d for d in decisions if d.get("status") == "pending"]

        return DashboardSummary(
            total_opportunities=len(opportunities),
            active_positions=len(positions),
            watchlist_count=len(watchlist),
            total_capital=cash.get("total_capital", 0),
            cash_balance=cash.get("cash_balance", 0),
            cash_pct=cash.get("cash_pct", 0),
            best_conviction=max(convictions) if convictions else 0,
            worst_conviction=min(convictions) if convictions else 0,
            recent_decisions=len(decisions),
            pending_decisions=len(pending),
            risk_alerts=len(risk_alerts),
        )
