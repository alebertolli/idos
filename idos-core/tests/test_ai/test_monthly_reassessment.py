from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, ANY

import pytest
import yaml

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.workers.ai.monthly_reassessment_worker import MonthlyReassessmentWorker
from idos.timezone import AR_TZ


def _seed_full_position(sqlite: SQLiteStore, journal: JournalRepository, bp: Path,
                        ticker: str, price: float = 100, intrinsic: float = 100,
                        conviction: int = 50, thesis_active: bool = True):
    from idos.portfolio.paper import PaperTrader
    opp_id = f"OPP-{ticker}-001"
    opp = {
        "id": opp_id,
        "ticker": ticker,
        "status": OpportunityStatus.FULL_POSITION.value,
        "conviction": {"overall": conviction},
        "intrinsic_value": intrinsic,
        "current_price": price,
        "entry_price": price,
        "stop_loss": 80,
        "thesis_active": thesis_active,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    sqlite.save_opportunity(opp)
    journal.save_opportunity(ticker, opp)

    # Create paper position so entry_price/stop_loss are available
    pos = {
        "ticker": ticker,
        "opp_id": opp_id,
        "entry_price": price,
        "quantity": 10,
        "total_invested": price * 10,
        "current_value": price * 10,
        "stop_loss": 80,
        "target_price": intrinsic,
        "entry_date": "2026-01-01T00:00:00",
        "conviction_at_entry": conviction,
    }
    pos_dir = journal.base / "paper" / "positions"
    pos_dir.mkdir(parents=True, exist_ok=True)
    (pos_dir / f"{ticker}.yml").write_text(yaml.dump(pos, default_flow_style=False), encoding="utf-8")
    return opp_id


def _seed_price(sqlite: SQLiteStore, ticker: str, price: float):
    sqlite.save_price_history(ticker, [{"date": "2026-06-01", "close": price}])


def _make_worker(bp: Path, **overrides) -> MonthlyReassessmentWorker:
    cfg = {"notify": False}
    cfg.update(overrides)
    return MonthlyReassessmentWorker(cfg)


class TestMonthlyReassessment:
    def test_recent_thesis_review_skips_llm_until_next_profile_date(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "DUE")
        now = datetime.now(AR_TZ)
        opp = sqlite.get_opportunity("OPP-DUE-001")
        opp["last_thesis_assessment_at"] = (now - timedelta(days=10)).isoformat()
        sqlite.save_opportunity(opp)
        journal.save_opportunity("DUE", opp)

        worker = _make_worker(bp)
        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            results = worker._reassess_theses([opp], sqlite, journal, bp)

        mock_cls.assert_not_called()
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "review_not_due"
        assert results[0]["next_thesis_review_at"] == (now + timedelta(days=20)).isoformat()

    def test_manual_ticker_scope_limits_all_monthly_reassessment_steps(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "AAA")
        _seed_full_position(sqlite, journal, bp, "BBB")
        _seed_price(sqlite, "AAA", 100)
        _seed_price(sqlite, "BBB", 100)

        worker = _make_worker(bp, portfolio={"runtime_enabled": True})
        seen = {}
        def record_scope(name):
            def record(opportunities, *args):
                seen[name] = [opportunity["ticker"] for opportunity in opportunities]
                return []
            return record

        with patch.object(worker, "_reassess_theses", side_effect=record_scope("thesis")), \
             patch.object(worker, "_recalibrate_conviction", side_effect=record_scope("conviction")), \
             patch.object(worker, "_review_portfolio", side_effect=record_scope("portfolio")):
            result = worker.execute({"base_path": str(bp), "tickers": ["aaa"]}).output

        assert result["total_active"] == 1
        assert seen == {"thesis": ["AAA"], "conviction": ["AAA"], "portfolio": ["AAA"]}

    def test_skip_portfolio_review_preserves_thesis_and_conviction_reassessment(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "AAA")
        worker = _make_worker(bp, portfolio={"runtime_enabled": True})

        with patch.object(worker, "_reassess_theses", return_value=[{"status": "completed"}]) as thesis, \
             patch.object(worker, "_recalibrate_conviction", return_value=[{"ticker": "AAA"}]) as conviction, \
             patch.object(worker, "_review_portfolio") as portfolio:
            result = worker.execute({
                "base_path": str(bp),
                "skip_portfolio_review": True,
            }).output

        thesis.assert_called_once()
        conviction.assert_called_once()
        portfolio.assert_not_called()
        assert result["thesis_reassessed"] == 1
        assert result["conviction_recalibrated"] == 1
        assert result["portfolio_reviewed"] == 0
        assert result["portfolio_review_status"] == "skipped_for_run"

    def test_invalidated_thesis_creates_sell_proposal_without_exiting(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "AAA", price=100, intrinsic=120, conviction=60)
        _seed_price(sqlite, "AAA", 100)

        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            mock_w = MagicMock()
            mock_w.run.return_value = {
                "status": "completed",
                "thesis_active": False,
                "reason": "moat destruido por competencia",
                "flags": ["moat_destruido"],
                "confidence": 0.8,
            }
            mock_cls.return_value = mock_w

            w = _make_worker(bp)
            r = w.execute({"base_path": str(bp)}).output

        assert r["total_active"] == 1
        assert r["thesis_reassessed"] == 1
        assert r["thesis_failed"] == 0
        assert r["thesis_changed"] == 1
        assert len(r["exit_proposals"]) == 1
        proposal = r["exit_proposals"][0]
        assert proposal["type"] == "SELL"
        assert proposal["status"] == "PENDING_REVIEW"
        assert proposal["human_approval_required"] is True
        opp = sqlite.get_opportunity("OPP-AAA-001")
        assert opp["status"] == "FULL_POSITION"
        assert opp["thesis_active"] is False
        assert not opp.get("exit_reason")
        assert datetime.fromisoformat(opp["next_thesis_review_at"]) > datetime.now(AR_TZ)
        journal_opp = journal.load_opportunity("AAA", "OPP-AAA-001")
        assert journal_opp["status"] == "FULL_POSITION"
        assert journal_opp["thesis_active"] is False
        assert journal_opp["next_thesis_review_at"] == opp["next_thesis_review_at"]
        transitions = list(sqlite.conn.execute(
            "SELECT id FROM state_transitions WHERE opportunity_id = ? AND to_status = 'EXITED'",
            ("OPP-AAA-001",),
        ))
        assert transitions == []

    def test_thesis_intact_no_exit(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "BBB", price=100, intrinsic=120, conviction=60)
        _seed_price(sqlite, "BBB", 100)

        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            mock_w = MagicMock()
            mock_w.run.return_value = {
                "status": "completed",
                "thesis_active": True,
                "reason": "", "flags": [], "confidence": 0.9,
            }
            mock_cls.return_value = mock_w

            w = _make_worker(bp)
            r = w.execute({"base_path": str(bp)}).output

        assert r["exit_proposals"] == []
        assert r["proposals"] == []
        opp = sqlite.get_opportunity("OPP-BBB-001")
        assert opp["status"] == "FULL_POSITION"
        assert opp["thesis_active"] is True

    def test_conviction_recalibration_overvalued(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "CCC", price=150, intrinsic=100, conviction=80)
        _seed_price(sqlite, "CCC", 150)

        w = _make_worker(bp)
        with patch.object(w, '_reassess_theses', return_value=[]):
            r = w.execute({"base_path": str(bp)}).output

        assert r["conviction_recalibrated"] == 1
        opp = sqlite.get_opportunity("OPP-CCC-001")
        assert opp["conviction"]["overall"] < 80

    def test_conviction_recalibration_undervalued(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "DDD", price=70, intrinsic=100, conviction=30)
        _seed_price(sqlite, "DDD", 70)

        w = _make_worker(bp)
        with patch.object(w, '_reassess_theses', return_value=[]):
            r = w.execute({"base_path": str(bp)}).output

        assert r["conviction_recalibrated"] == 1
        opp = sqlite.get_opportunity("OPP-DDD-001")
        assert opp["conviction"]["overall"] > 30

    def test_portfolio_proposal_generated(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "EEE", price=100, intrinsic=110, conviction=40)
        _seed_price(sqlite, "EEE", 100)

        bl_dir = bp / "idos-journal" / "portfolio"
        bl_dir.mkdir(parents=True, exist_ok=True)
        (bl_dir / "buylist.yml").write_text(yaml.dump({
            "entries": [{"ticker": "FFF", "conviction_score": 90}],
        }, default_flow_style=False), encoding="utf-8")

        w = _make_worker(bp, portfolio={"runtime_enabled": True})
        with patch.object(w, '_reassess_theses', return_value=[]), \
             patch.object(w, '_recalibrate_conviction', return_value=[]):
            r = w.execute({"base_path": str(bp)}).output

        assert len(r["proposals"]) == 1
        assert r["proposals"][0]["ticker"] == "EEE"

    def test_portfolio_no_proposal_when_no_candidate(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "GGG", price=100, intrinsic=200, conviction=80)
        _seed_price(sqlite, "GGG", 100)

        w = _make_worker(bp, portfolio={"runtime_enabled": True})
        with patch.object(w, '_reassess_theses', return_value=[]), \
             patch.object(w, '_recalibrate_conviction', return_value=[]):
            r = w.execute({"base_path": str(bp)}).output

        assert len(r["proposals"]) == 0

    def test_portfolio_review_is_disabled_by_default(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "NO_PORTFOLIO")

        worker = _make_worker(bp)
        with patch.object(worker, "_review_portfolio") as review:
            result = worker.execute({"base_path": str(bp)}).output

        review.assert_not_called()
        assert result["portfolio_reviewed"] == 0
        assert result["portfolio_review_status"] == "disabled"

    def test_cache_written(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "HHH", price=100, intrinsic=100, conviction=50)
        _seed_price(sqlite, "HHH", 100)

        w = _make_worker(bp)
        with patch.object(w, '_reassess_theses', return_value=[]):
            w.execute({"base_path": str(bp)})

        cache_file = bp / "cache" / "monthly_reassessment.json"
        assert cache_file.exists()
        import json
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "summary" in data
        assert "thesis_results" in data
        assert "conviction_results" in data
        assert "portfolio_results" in data

    def test_no_active_positions_skips_gracefully(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")

        w = _make_worker(bp)
        r = w.execute({"base_path": str(bp)}).output

        assert r["total_active"] == 0
        assert r["exit_proposals"] == []

    def test_thesis_error_handled(self, tmp_path: Path):
        bp = tmp_path
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        _seed_full_position(sqlite, journal, bp, "III", price=100, intrinsic=100, conviction=50)
        _seed_price(sqlite, "III", 100)

        with patch("idos.workers.ai.thesis_monitor_worker.ThesisMonitorWorker") as mock_cls:
            mock_w = MagicMock()
            mock_w.run.side_effect = Exception("LLM timeout")
            mock_cls.return_value = mock_w

            w = _make_worker(bp)
            r = w.execute({"base_path": str(bp)}).output

        assert r["thesis_reassessed"] == 0
        assert r["thesis_failed"] == 1
        assert r["thesis_changed"] == 0
        opp = sqlite.get_opportunity("OPP-III-001")
        assert opp["status"] == "FULL_POSITION"
