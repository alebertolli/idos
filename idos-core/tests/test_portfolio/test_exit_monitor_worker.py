from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.paper import PaperTrader
from idos.workers.portfolio.exit_monitor_worker import ExitMonitorWorker


def _make_position(journal: JournalRepository, ticker: str, price: float, qty: int = 10):
    trader = PaperTrader({
        "bankroll": 100000,
        "max_position_pct": 3.0,
        "fee_pct": 0.1,
        "stop_loss_asymmetry_divisor": 3,
    }, journal)
    trader.buy(ticker, price, conviction=50, opp_id=f"OPP-{ticker}-001", intrinsic_value=price * 1.5)
    return trader


def _seed_opp(sqlite: SQLiteStore, ticker: str, **overrides):
    opp = {
        "id": f"OPP-{ticker}-001",
        "ticker": ticker,
        "status": "FULL_POSITION",
        "conviction": {"overall": 50},
        "intrinsic_value": 100.0,
        "thesis_active": True,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    opp.update(overrides)
    sqlite.save_opportunity(opp)
    return opp


def _seed_price(sqlite: SQLiteStore, ticker: str, price: float):
    sqlite.save_price_history(ticker, [{"date": "2026-01-10", "close": price}])


def _worker(bp: Path, **cfg) -> ExitMonitorWorker:
    base = {
        "exit": {
            "valuation_overvaluation_pct": 25,
            "exit_pct_on_valuation": 50,
            "replacement_conviction_multiple": 1.3,
            "min_asymmetry_ratio": 3,
            "notify": False,
        },
        "risk": {"max_drawdown_pct": 15.0},
        "risk_reassessment_cooldown_days": 7,
    }
    base.update(cfg)
    return ExitMonitorWorker(base)


class TestExitMonitorWorker:
    def test_thesis_exit_sells_100(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "AAA", price=100)
        _seed_opp(sqlite, "AAA", thesis_active=False, thesis_invalidated_reason="falsacion")
        _seed_price(sqlite, "AAA", 100)

        w = _worker(bp)
        result = w.execute({"base_path": str(bp)})
        r = result.output

        assert r["exits_executed"] == 1
        ex = r["exits"][0]
        assert ex["ticker"] == "AAA"
        assert ex["reason"] == "THESIS_INVALIDATED"
        assert ex["exit_pct"] == 1.0
        assert ex["new_status"] == "EXITED"
        assert not (bp / "idos-journal" / "paper" / "positions" / "AAA.yml").exists()

        opp = sqlite.get_opportunity("OPP-AAA-001")
        assert opp["status"] == "EXITED"
        assert opp["exit_reason"] == "THESIS_INVALIDATED"

        signals = yaml.safe_load((bp / "cache" / "exit_signals.json").read_text(encoding="utf-8"))
        assert len(signals["exits"]) == 1

    def test_thesis_active_keeps_position(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "BBB", price=100)
        _seed_opp(sqlite, "BBB", thesis_active=True)
        _seed_price(sqlite, "BBB", 100)

        w = _worker(bp)
        r = w.execute({"base_path": str(bp)}).output

        assert r["exits_executed"] == 0
        assert (bp / "idos-journal" / "paper" / "positions" / "BBB.yml").exists()
        assert sqlite.get_opportunity("OPP-BBB-001")["status"] == "FULL_POSITION"

    def test_valuation_exit_partial_never_full(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "CCC", price=100)
        _seed_opp(sqlite, "CCC", intrinsic_value=100)
        _seed_price(sqlite, "CCC", 140)  # overvaluation 40% >= 25%

        w = _worker(bp)
        r = w.execute({"base_path": str(bp)}).output

        assert r["exits_executed"] == 1
        ex = r["exits"][0]
        assert ex["reason"] == "VALUATION_EXCESSIVE"
        assert ex["exit_pct"] < 1.0
        assert ex["new_status"] == "REDUCING"

        pos_file = bp / "idos-journal" / "paper" / "positions" / "CCC.yml"
        assert pos_file.exists()
        pos = yaml.safe_load(pos_file.read_text(encoding="utf-8"))
        assert pos["quantity"] < 29

    def test_valuation_under_threshold_holds(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "DDD", price=100)
        _seed_opp(sqlite, "DDD", intrinsic_value=100)
        _seed_price(sqlite, "DDD", 110)  # overvaluation 10% < 25%

        w = _worker(bp)
        r = w.execute({"base_path": str(bp)}).output
        assert r["exits_executed"] == 0

    def test_risk_trigger_reassessment_changes_thesis(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "EEE", price=100)
        _seed_opp(sqlite, "EEE", thesis_active=True, intrinsic_value=100)
        _seed_price(sqlite, "EEE", 80)  # drawdown 20% > 15%

        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            mock_worker = MagicMock()
            mock_worker.run.return_value = {
                "status": "completed", "thesis_active": False,
                "flags": ["fin_crecimiento_estructural"], "reason": "Tesis cambiada",
            }
            mock_cls.return_value = mock_worker

            w = _worker(bp)
            r = w.execute({"base_path": str(bp)}).output

        assert r["exits_executed"] == 1
        assert r["exits"][0]["reason"] == "RISK_CONTROL"
        assert r["exits"][0]["exit_pct"] == 1.0

    def test_risk_trigger_no_thesis_change_keeps_position(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "FFF", price=100)
        _seed_opp(sqlite, "FFF", thesis_active=True, intrinsic_value=100)
        _seed_price(sqlite, "FFF", 80)  # drawdown 20%

        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            mock_worker = MagicMock()
            mock_worker.run.return_value = {
                "status": "completed", "thesis_active": True, "flags": [], "reason": "",
            }
            mock_cls.return_value = mock_worker

            w = _worker(bp)
            r = w.execute({"base_path": str(bp)}).output

        assert r["exits_executed"] == 0
        assert (bp / "idos-journal" / "paper" / "positions" / "FFF.yml").exists()

    def test_portfolio_proposal_no_auto_liquidation(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "GGG", price=100)
        _seed_opp(sqlite, "GGG", conviction={"overall": 40}, intrinsic_value=110)
        _seed_price(sqlite, "GGG", 100)

        bl_dir = bp / "idos-journal" / "portfolio"
        bl_dir.mkdir(parents=True, exist_ok=True)
        (bl_dir / "buylist.yml").write_text(yaml.dump({
            "entries": [{"ticker": "HHI", "conviction_score": 90}],
        }, default_flow_style=False), encoding="utf-8")

        w = _worker(bp)
        r = w.execute({"base_path": str(bp)}).output

        assert r["exits_executed"] == 0
        assert r["proposals_generated"] == 1
        prop = r["proposals"][0]
        assert prop["ticker"] == "GGG"
        assert prop["action"] == "proposal"
        # position sigue intacta
        assert (bp / "idos-journal" / "paper" / "positions" / "GGG.yml").exists()
        assert sqlite.get_opportunity("OPP-GGG-001")["status"] == "FULL_POSITION"

    def test_portfolio_proposal_not_generated_when_asymmetry_high(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _make_position(journal, "III", price=100)
        _seed_opp(sqlite, "III", conviction={"overall": 40}, intrinsic_value=300)
        _seed_price(sqlite, "III", 100)

        bl_dir = bp / "idos-journal" / "portfolio"
        bl_dir.mkdir(parents=True, exist_ok=True)
        (bl_dir / "buylist.yml").write_text(yaml.dump({
            "entries": [{"ticker": "JHJ", "conviction_score": 90}],
        }, default_flow_style=False), encoding="utf-8")

        w = _worker(bp)
        r = w.execute({"base_path": str(bp)}).output

        assert r["proposals_generated"] == 0
        assert r["exits_executed"] == 0
