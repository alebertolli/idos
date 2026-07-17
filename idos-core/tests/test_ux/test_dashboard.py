import pytest
from idos.ux.dashboard import DashboardAPI


class TestDashboardAPI:
    def test_build_summary(self):
        api = DashboardAPI()
        summary = api.build_summary(
            opportunities=[{"id": "1"}, {"id": "2"}],
            positions=[{"ticker": "AAPL", "conviction": 80}],
            watchlist=[{"ticker": "MSFT"}],
            decisions=[{"status": "pending"}, {"status": "approved"}],
            risk_alerts=[{"type": "drawdown"}],
            cash={"total_capital": 100_000, "cash_balance": 10_000, "cash_pct": 10},
        )
        assert summary.total_opportunities == 2
        assert summary.active_positions == 1
        assert summary.watchlist_count == 1
        assert summary.cash_pct == 10
        assert summary.best_conviction == 80
        assert summary.worst_conviction == 80
        assert summary.pending_decisions == 1
        assert summary.risk_alerts == 1

    def test_empty_summary(self):
        api = DashboardAPI()
        summary = api.build_summary(opportunities=[])
        assert summary.total_opportunities == 0
        assert summary.active_positions == 0
