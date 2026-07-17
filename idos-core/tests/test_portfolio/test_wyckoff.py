import pytest
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase


class TestWyckoffAnalyzer:
    def test_unknown_on_insufficient_data(self):
        wa = WyckoffAnalyzer()
        assert wa.analyze([]) == WyckoffPhase.UNKNOWN
        assert wa.analyze([{"close": 100}] * 10) == WyckoffPhase.UNKNOWN

    def test_markup_detected(self):
        prices = [{"close": 100 + i * 3, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        phase = wa.analyze(prices)
        assert phase == WyckoffPhase.MARKUP

    def test_markdown_detected(self):
        prices = [{"close": 200 - i * 4, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        phase = wa.analyze(prices)
        assert phase == WyckoffPhase.MARKDOWN

    def test_accumulation_after_markdown(self):
        prices = []
        for i in range(40):
            prices.append({"close": 200 - i * 5, "volume": 5000})
        for i in range(30):
            prices.append({"close": 15 + (i % 5) * 0.5, "volume": 700})
        wa = WyckoffAnalyzer()
        phase = wa.analyze(prices)
        assert phase == WyckoffPhase.ACCUMULATION

    def test_entry_confirmed_for_accumulation(self):
        wa = WyckoffAnalyzer()
        assert wa.is_entry_confirmed(WyckoffPhase.ACCUMULATION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.ABSORPTION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.MARKUP) is False
        assert wa.is_entry_confirmed(WyckoffPhase.DISTRIBUTION) is False
