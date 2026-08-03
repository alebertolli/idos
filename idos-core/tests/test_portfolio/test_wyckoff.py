import pytest
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase


class TestWyckoffAnalyzer:
    def test_unknown_on_insufficient_data(self):
        wa = WyckoffAnalyzer()
        assert wa.analyze([]).phase == WyckoffPhase.UNKNOWN
        assert wa.analyze([{"close": 100}] * 10).phase == WyckoffPhase.UNKNOWN

    def test_uptrend_detected_as_accumulation(self):
        prices = [{"close": 100 + i * 3, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.phase == WyckoffPhase.ACCUMULATION
        assert result.score >= 65

    def test_downtrend_detected_as_distribution(self):
        prices = [{"close": 200 - i * 4, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.phase == WyckoffPhase.DISTRIBUTION
        assert result.score < 25

    def test_entry_confirmed_for_accumulation(self):
        wa = WyckoffAnalyzer()
        assert wa.is_entry_confirmed(WyckoffPhase.ACCUMULATION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.ABSORPTION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.MARKUP) is False
        assert wa.is_entry_confirmed(WyckoffPhase.DISTRIBUTION) is False

    def test_band_classification(self):
        wa = WyckoffAnalyzer(bands={"demand": 65, "absorption": 45, "supply": 25})
        assert wa._classify(70) == WyckoffPhase.ACCUMULATION
        assert wa._classify(55) == WyckoffPhase.ABSORPTION
        assert wa._classify(35) == WyckoffPhase.MARKDOWN
        assert wa._classify(15) == WyckoffPhase.DISTRIBUTION

    def test_composite_score_respects_weights(self):
        wa = WyckoffAnalyzer()
        components = {"structure": 100.0, "supply_demand": 100.0,
                      "relative_strength": 100.0, "volatility": 100.0}
        assert wa._composite_score(components) == 100
        components = {"structure": 0.0, "supply_demand": 0.0,
                      "relative_strength": 0.0, "volatility": 0.0}
        assert wa._composite_score(components) == 0

    def test_relative_strength_vs_benchmark(self):
        wa = WyckoffAnalyzer()
        closes = list(range(100, 200))
        benchmark = list(range(100, 120))  # ticker outperform
        score = wa._score_relative_strength(closes, [{"close": c} for c in benchmark])
        assert score > 50
        declining = list(range(200, 100, -1))
        strong_bench = list(range(100, 200))
        weak = wa._score_relative_strength(declining, [{"close": c} for c in strong_bench])
        assert weak < 50

    def test_indicators_output(self):
        prices = [{"close": 100 + i * 3, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.indicators
        assert result.indicators["algorithmic_phase"] == result.phase.value
        assert result.indicators["composite_score"] == result.score
        assert "component_scores" in result.indicators
