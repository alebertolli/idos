import pytest
from idos.portfolio.rebalance import PortfolioRebalancer


class TestPortfolioRebalancer:
    def test_position_weight_exceeded(self):
        pr = PortfolioRebalancer(max_position_pct=3)
        proposals = pr.evaluate(
            [{"ticker": "AAPL", "weight_pct": 5, "sector": "Tech"}],
            {},
        )
        assert len(proposals) == 1
        assert proposals[0].action == "REDUCE"
        assert proposals[0].ticker == "AAPL"

    def test_conviction_drop(self):
        pr = PortfolioRebalancer(conviction_drop_threshold=10)
        proposals = pr.evaluate(
            [{"ticker": "AAPL", "weight_pct": 2, "sector": "Tech"}],
            {"AAPL": -15},
        )
        assert len(proposals) == 1
        assert proposals[0].action == "REDUCE"

    def test_sector_alert(self):
        pr = PortfolioRebalancer(max_sector_pct=25)
        proposals = pr.evaluate([
            {"ticker": "AAPL", "weight_pct": 15, "sector": "Tech"},
            {"ticker": "MSFT", "weight_pct": 15, "sector": "Tech"},
        ], {})
        assert any(p.ticker == "SECTOR:Tech" for p in proposals)
