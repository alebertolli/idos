import pytest
from idos.portfolio.entry import EntryEngine, EntrySignal


class TestEntryEngine:
    def test_entry_basic_accept(self):
        prices = [{"close": 20 + i * 1.5, "volume": 3000} for i in range(20)]
        prices += [{"close": 50 + i * 3, "volume": 5000} for i in range(30)]
        engine = EntryEngine(min_margin_of_safety=20)
        signal = engine.evaluate("AAPL", {
            "price_data": prices,
            "intrinsic_value": 200,
            "current_price": 100,
            "thesis_active": True,
            "portfolio": {"total_weight": 0},
            "proposed_weight": 3.0,
        })
        assert signal.ticker == "AAPL"
        assert signal.price_in_zone is True
        assert signal.wyckoff_confirmed is True
        assert signal.all_conditions_met is True

    def test_entry_blocked_by_price(self):
        engine = EntryEngine(min_margin_of_safety=50)
        signal = engine.evaluate("AAPL", {
            "price_data": [{"close": 100, "volume": 1000}] * 50,
            "intrinsic_value": 120,
            "current_price": 100,
            "thesis_active": True,
            "portfolio": {"total_weight": 0},
        })
        assert signal.all_conditions_met is False
        assert signal.price_in_zone is False

    def test_entry_blocked_by_portfolio_weight(self):
        engine = EntryEngine()
        signal = engine.evaluate("AAPL", {
            "price_data": [{"close": 100, "volume": 1000}] * 50,
            "intrinsic_value": 200,
            "current_price": 100,
            "thesis_active": True,
            "portfolio": {"total_weight": 19},
            "proposed_weight": 3.0,
        })
        assert signal.all_conditions_met is False
        assert signal.portfolio_fit is False
