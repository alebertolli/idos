import pytest
from idos.portfolio.diversification import DiversificationController


class TestDiversificationController:
    def test_sector_passes(self):
        dc = DiversificationController(max_sector_pct=25)
        result = dc.check_sector("Tech", 20, 3)
        assert result["passed"] is True

    def test_sector_fails(self):
        dc = DiversificationController(max_sector_pct=25)
        result = dc.check_sector("Tech", 24, 5)
        assert result["passed"] is False

    def test_position_fails(self):
        dc = DiversificationController(max_single_position=3)
        result = dc.check_position(2.5, 1.0)
        assert result["passed"] is False

    def test_count_fails(self):
        dc = DiversificationController(max_positions=20)
        assert dc.check_count(20)["passed"] is False
        assert dc.check_count(15)["passed"] is True

    def test_thematic_exposure_tracking(self):
        dc = DiversificationController()
        dc.register_theme_exposure("AI", 5.0)
        dc.register_theme_exposure("AI", 3.0)
        assert dc.get_theme_exposures() == {"AI": 8.0}
