from pathlib import Path

import pytest
import yaml

from idos.data.journal import JournalRepository
from idos.models.enums import OpportunityStatus
from idos.workers.portfolio.buy_list_refresh_worker import BuyListRefreshWorker


@pytest.fixture
def buylist_env(tmp_path: Path):
    sqlite_path = tmp_path / "idos.db"
    from idos.data.sqlite import SQLiteStore
    db = SQLiteStore(sqlite_path)
    journal = JournalRepository(tmp_path / "idos-journal")

    for i, ticker in enumerate(["AAPL", "MSFT"]):
        opp_id = f"OPP-BL-{i}"
        db.save_opportunity({
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.APPROVED.value,
            "conviction": {"overall": 80, "intrinsic_value": 220, "current_price": 150},
            "intrinsic_value": 220,
            "current_price": 150,
            "horizon": "12-36 months",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        })
        journal.save_opportunity(ticker, db.get_opportunity(opp_id))
    return db, journal, tmp_path


class TestBuyListRefreshWorker:
    def test_writes_buylist_yml(self, buylist_env, tmp_path: Path):
        db, journal, bp = buylist_env
        w = BuyListRefreshWorker()
        result = w.execute({"base_path": str(bp)})
        assert result.status == "success"
        r = result.output
        assert r["status"] == "completed"
        assert r["added"] == 2

        buylist_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        assert buylist_path.exists(), "buylist.yml should be written"
        data = yaml.safe_load(buylist_path.read_text(encoding="utf-8"))
        entries = {e["ticker"]: e for e in data["entries"]}
        assert "AAPL" in entries and "MSFT" in entries
        assert entries["AAPL"]["target_price"] == pytest.approx(220.0)
        assert entries["AAPL"]["buy_zone_top"] == pytest.approx(154.0)  # 220 * 0.7

    def test_preserves_opp_id_and_monitoring(self, buylist_env, tmp_path: Path):
        db, journal, bp = buylist_env
        buylist_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        buylist_path.parent.mkdir(parents=True, exist_ok=True)
        buylist_path.write_text(yaml.dump({
            "entries": [{
                "ticker": "AAPL",
                "opp_id": "OPP-BL-0",
                "target_price": 0,
                "buy_zone_top": 0,
                "max_position_pct": 3.0,
                "conviction_score": 80,
                "horizon": "12-36 months",
                "catalysts": [],
                "kb_last_update": "",
                "added_at": "",
                "monitoring": True,
            }]
        }), encoding="utf-8")

        w = BuyListRefreshWorker()
        result = w.execute({"base_path": str(bp)})
        r = result.output
        assert r["status"] == "completed"
        assert r["updated"] == 1
        assert r["added"] == 1

        data = yaml.safe_load(buylist_path.read_text(encoding="utf-8"))
        entries = {e["ticker"]: e for e in data["entries"]}
        assert entries["AAPL"]["opp_id"] == "OPP-BL-0"
        assert entries["AAPL"]["monitoring"] is True
        assert entries["MSFT"]["monitoring"] is True
