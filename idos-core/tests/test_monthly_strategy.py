from pathlib import Path

from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker, momentum_score


class FakePrices:
    def __init__(self):
        self.requested = []

    def get_history(self, ticker, period="2y", interval="1mo"):
        self.requested.append(ticker)
        return [{"date": f"2026-{(i % 12) + 1:02d}-01", "close": 100 + 2 * i, "volume": 1} for i in range(24)]


def add_allowlist(tmp_path: Path, tickers=None):
    import yaml

    path = tmp_path / "idos-config" / "universe" / "operable.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"ticker": ticker} for ticker in (tickers or ["QQQ", "XLE", "XLF", "XLI", "EFA", "EEM", "GLD"])]
    path.write_text(yaml.safe_dump({"operable_tickers": entries}), encoding="utf-8")


def test_momentum_score_requires_history():
    try:
        momentum_score([1.0] * 12)
    except ValueError:
        pass
    else:
        raise AssertionError("short history must be rejected")


def test_monthly_strategy_dry_run_does_not_persist(tmp_path: Path):
    add_allowlist(tmp_path)
    worker = MonthlyStrategyWorker({"price_provider": FakePrices()})
    result = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})
    assert result["strategy_id"] == "MOMENTUM_ETF"
    assert not (tmp_path / "idos-journal").exists()


def test_monthly_strategy_persists_signal_in_sqlite(tmp_path: Path):
    add_allowlist(tmp_path)
    worker = MonthlyStrategyWorker({"price_provider": FakePrices()})
    worker.run({"base_path": str(tmp_path), "persist": True})
    from idos.data.sqlite import SQLiteStore
    store = SQLiteStore(tmp_path / "idos.db")
    rows = list(store.conn.execute("SELECT id FROM opportunities"))
    assert rows
    opp = store.get_opportunity(rows[0][0])
    assert opp["signal"]["momentum"] is not None
    assert opp["status"] == "SCREENED"


def test_monthly_rerun_preserves_reviewed_status(tmp_path: Path):
    from idos.data.sqlite import SQLiteStore

    add_allowlist(tmp_path)
    worker = MonthlyStrategyWorker({"price_provider": FakePrices()})
    worker.run({"base_path": str(tmp_path), "persist": True})
    store = SQLiteStore(tmp_path / "idos.db")
    opp_id = store.conn.execute("SELECT id FROM opportunities").fetchone()[0]
    opp = store.get_opportunity(opp_id)
    opp["status"] = "UNDER_RESEARCH"
    store.save_opportunity(opp)
    worker.run({"base_path": str(tmp_path), "persist": True})
    assert store.get_opportunity(opp_id)["status"] == "UNDER_RESEARCH"


def test_monthly_strategy_filters_universe_before_price_fetch(tmp_path: Path):
    add_allowlist(tmp_path, ["QQQ"])
    prices = FakePrices()
    result = MonthlyStrategyWorker({"price_provider": prices}).run(
        {"base_path": str(tmp_path), "dry_run": True, "persist": False}
    )

    assert prices.requested == ["QQQ"]
    assert [row["ticker"] for row in result["ranking"]] == ["QQQ"]
    assert result["ineligible_universe"] == ["XLE", "XLF", "XLI", "EFA", "EEM", "GLD"]
