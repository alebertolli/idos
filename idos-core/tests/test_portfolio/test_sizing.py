import pytest
from idos.portfolio.sizing import PositionSizer


class TestPositionSizer:
    def test_kelly_zero_on_bad_inputs(self):
        ps = PositionSizer()
        assert ps.kelly_size(tsp=0, payoff_ratio=2, bankroll=100_000) == 0
        assert ps.kelly_size(tsp=0.5, payoff_ratio=0, bankroll=100_000) == 0

    def test_kelly_size_capped(self):
        ps = PositionSizer(max_position_pct=3.0)
        size = ps.kelly_size(tsp=0.8, payoff_ratio=2, bankroll=100_000)
        assert size <= 3_000

    def test_kelly_size(self):
        ps = PositionSizer(max_position_pct=50)
        size = ps.kelly_size(tsp=0.6, payoff_ratio=1.5, bankroll=100_000)
        assert 0 < size <= 50_000

    def test_calculate_max_size(self):
        ps = PositionSizer(max_position_pct=5)
        suggested, dollars = ps.calculate_max_size(conviction=80, bankroll=200_000, current_weight=2)
        assert suggested > 0
        assert dollars > 0
        assert suggested + 2 <= 5

    def test_calculate_max_size_at_limit(self):
        ps = PositionSizer(max_position_pct=3)
        suggested, _ = ps.calculate_max_size(conviction=80, bankroll=100_000, current_weight=3)
        assert suggested == 0
