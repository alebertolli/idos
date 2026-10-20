import pytest
from idos.portfolio.competition import CapitalCompetitionEngine


class TestCapitalCompetitionEngine:
    def test_replace_worst(self):
        cce = CapitalCompetitionEngine(replacement_threshold=1.3)
        result = cce.evaluate(
            {"ticker": "NVDA", "conviction": 80},
            [{"ticker": "SLOW", "conviction": 50}],
        )
        assert result.should_replace is True
        assert result.new_opportunity == "NVDA"
        assert result.worst_position == "SLOW"

    def test_no_replacement_needed(self):
        cce = CapitalCompetitionEngine(replacement_threshold=1.5)
        result = cce.evaluate(
            {"ticker": "NVDA", "conviction": 60},
            [{"ticker": "SLOW", "conviction": 50}],
        )
        assert result.should_replace is False

    def test_no_active_positions(self):
        cce = CapitalCompetitionEngine()
        result = cce.evaluate({"ticker": "NVDA", "conviction": 80}, [])
        assert result.should_replace is False
        assert result.worst_position == ""
