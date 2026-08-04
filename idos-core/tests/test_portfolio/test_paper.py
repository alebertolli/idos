from pathlib import Path

import pytest
import yaml

from idos.data.journal import JournalRepository
from idos.portfolio.paper import PaperTrader


def _trader(tmp_path: Path) -> tuple[PaperTrader, JournalRepository]:
    journal = JournalRepository(tmp_path / "idos-journal")
    trader = PaperTrader({
        "bankroll": 100000,
        "max_position_pct": 3.0,
        "fee_pct": 0.1,
        "stop_loss_asymmetry_divisor": 3,
    }, journal)
    return trader, journal


class TestPaperPartialSell:
    def test_sell_full_removes_position(self, tmp_path: Path):
        trader, journal = _trader(tmp_path)
        trader.buy("AAA", price=100, conviction=50, opp_id="OPP-AAA-001", intrinsic_value=150)
        pos_file = journal.base / "paper" / "positions" / "AAA.yml"
        assert pos_file.exists()

        result = trader.sell("AAA", price=110, reason="thesis_broken", exit_pct=1.0)
        assert result["status"] == "executed"
        assert result["closed"] is True
        assert not pos_file.exists()

    def test_sell_partial_keeps_remaining(self, tmp_path: Path):
        trader, journal = _trader(tmp_path)
        trader.buy("BBB", price=100, conviction=50, opp_id="OPP-BBB-001", intrinsic_value=150)
        buy_pos = yaml.safe_load((journal.base / "paper" / "positions" / "BBB.yml").read_text(encoding="utf-8"))
        original_qty = buy_pos["quantity"]
        assert original_qty > 1

        result = trader.sell("BBB", price=100, reason="valuation_excessive", exit_pct=0.5)
        assert result["status"] == "executed"
        assert result["closed"] is False
        assert result["quantity"] == original_qty // 2

        pos = yaml.safe_load((journal.base / "paper" / "positions" / "BBB.yml").read_text(encoding="utf-8"))
        assert pos["quantity"] == original_qty - result["quantity"]
        assert pos["opp_id"] == "OPP-BBB-001"
        assert pos["total_invested"] < buy_pos["total_invested"]

    def test_sell_partial_then_full(self, tmp_path: Path):
        trader, journal = _trader(tmp_path)
        trader.buy("CCC", price=100, conviction=50, opp_id="OPP-CCC-001", intrinsic_value=150)
        pos_file = journal.base / "paper" / "positions" / "CCC.yml"
        qty = yaml.safe_load(pos_file.read_text(encoding="utf-8"))["quantity"]

        r1 = trader.sell("CCC", price=100, reason="valuation_excessive", exit_pct=0.5)
        assert r1["closed"] is False
        assert pos_file.exists()

        r2 = trader.sell("CCC", price=120, reason="thesis_broken", exit_pct=1.0)
        assert r2["status"] == "executed"
        assert r2["closed"] is True
        assert not pos_file.exists()
        assert r2["quantity"] == qty - r1["quantity"]

    def test_sell_exit_pct_clamped(self, tmp_path: Path):
        trader, journal = _trader(tmp_path)
        trader.buy("DDD", price=100, conviction=50, opp_id="OPP-DDD-001", intrinsic_value=150)
        result = trader.sell("DDD", price=100, reason="test", exit_pct=1.5)
        assert result["closed"] is True
        assert not (journal.base / "paper" / "positions" / "DDD.yml").exists()

    def test_sell_no_position_skipped(self, tmp_path: Path):
        trader, _ = _trader(tmp_path)
        result = trader.sell("ZZZ", price=100, reason="test", exit_pct=1.0)
        assert result["status"] == "skipped"
