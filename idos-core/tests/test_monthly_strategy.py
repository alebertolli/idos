from pathlib import Path

from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker, momentum_score


class FakePrices:
    def __init__(self):
        self.tickers = []

    def get_history(self, ticker, period="2y", interval="1mo"):
        self.tickers.append(ticker)
        return [{"date": f"2026-{(i % 12) + 1:02d}-01", "close": 100 + 2 * i, "volume": 1} for i in range(24)]


def test_momentum_score_requires_history():
    try:
        momentum_score([1.0] * 12)
    except ValueError:
        pass
    else:
        raise AssertionError("short history must be rejected")


def test_monthly_strategy_dry_run_does_not_persist(tmp_path: Path):
    worker = MonthlyStrategyWorker({"price_provider": FakePrices()})
    result = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})
    assert result["strategy_id"] == "MOMENTUM_ETF"
    assert not (tmp_path / "idos-journal").exists()


def test_monthly_strategy_persists_signal_in_sqlite(tmp_path: Path):
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

    worker = MonthlyStrategyWorker({"price_provider": FakePrices()})
    worker.run({"base_path": str(tmp_path), "persist": True})
    store = SQLiteStore(tmp_path / "idos.db")
    opp_id = store.conn.execute("SELECT id FROM opportunities").fetchone()[0]
    opp = store.get_opportunity(opp_id)
    opp["status"] = "UNDER_RESEARCH"
    store.save_opportunity(opp)
    worker.run({"base_path": str(tmp_path), "persist": True})
    assert store.get_opportunity(opp_id)["status"] == "UNDER_RESEARCH"


def test_momentum_strategy_intersects_configured_universe_with_operable_registry(tmp_path: Path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\n"
        "default_strategy: MOMENTUM_ETF\n"
        "strategies:\n"
        "  MOMENTUM_ETF:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n"
        "    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n"
        "    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n"
        "    parameters:\n"
        "      universe: [QQQ, XLE]\n"
        "      select_top: 2\n"
        "      minimum_signal: 0.6\n"
        "      maximum_signal: 2.7\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: XLE\n    type: us_equity\n  - ticker: AAPL\n    type: us_equity\n",
        encoding="utf-8",
    )
    prices = FakePrices()
    worker = MonthlyStrategyWorker({"config_path": str(config_dir / "strategies.yml"), "price_provider": prices})

    output = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})

    assert prices.tickers == ["XLE"]
    assert output["candidate_tickers"] == ["XLE"]
    assert output["candidate_count"] == 1
    assert output["excluded_not_operable"] == ["QQQ"]
