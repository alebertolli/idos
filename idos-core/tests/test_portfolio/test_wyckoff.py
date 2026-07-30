import pytest
from idos.portfolio.wyckoff import WyckoffAnalyzer, WyckoffPhase


class TestWyckoffAnalyzer:
    def test_unknown_on_insufficient_data(self):
        wa = WyckoffAnalyzer()
        assert wa.analyze([]).phase == WyckoffPhase.UNKNOWN
        assert wa.analyze([{"close": 100}] * 10).phase == WyckoffPhase.UNKNOWN

    def test_markup_detected(self):
        prices = [{"close": 100 + i * 3, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.phase == WyckoffPhase.MARKUP

    def test_markdown_detected(self):
        prices = [{"close": 200 - i * 4, "volume": 1000} for i in range(50)]
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.phase == WyckoffPhase.MARKDOWN

    def test_accumulation_after_markdown(self):
        prices = []
        for i in range(40):
            prices.append({"close": 200 - i * 5, "volume": 5000})
        for i in range(30):
            prices.append({"close": 15 + (i % 5) * 0.5, "volume": 700})
        wa = WyckoffAnalyzer()
        result = wa.analyze(prices)
        assert result.phase == WyckoffPhase.ACCUMULATION

    def test_entry_confirmed_for_accumulation(self):
        wa = WyckoffAnalyzer()
        assert wa.is_entry_confirmed(WyckoffPhase.ACCUMULATION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.ABSORPTION) is True
        assert wa.is_entry_confirmed(WyckoffPhase.MARKUP) is False
        assert wa.is_entry_confirmed(WyckoffPhase.DISTRIBUTION) is False

    def test_wyckoff_score_weighting(self):
        wa = WyckoffAnalyzer()
        score = wa._compute_wyckoff_score(
            phase=WyckoffPhase.ACCUMULATION,
            raw_llm=None,
            confidence_label="alta",
            entry_point="lps",
        )
        assert score == 60  # 30 (phase) + 0 (no pruebas) + 15 (alta) + 15 (lps)

    def test_wyckoff_score_with_full_data(self):
        wa = WyckoffAnalyzer()
        from tests.conftest import MOCK_ENTRY_LLM_RESPONSE
        score = wa._compute_wyckoff_score(
            phase=WyckoffPhase.ACCUMULATION,
            raw_llm=MOCK_ENTRY_LLM_RESPONSE,
            confidence_label="alta",
            entry_point="lps",
        )
        # 30 (phase) + 22 (pruebas 8/9*25) + 15 (alta) + 15 (lps) + 9 (3 eventos*3) = 91
        assert score == 91
