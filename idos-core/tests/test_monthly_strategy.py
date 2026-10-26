from pathlib import Path

from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker, momentum_score


class FakePrices:
    def __init__(self):
        self.tickers = []

    def get_history(self, ticker, period="2y", interval="1mo"):
        self.tickers.append(ticker)
        return [{"date": f"2026-{(i % 12) + 1:02d}-01", "close": 100 + 2 * i, "volume": 1} for i in range(24)]


class FakeMarketGate:
    def __init__(self, dollar_volume=200_000):
        self.dollar_volume = dollar_volume
        self.tickers = []

    def execute(self, context):
        from types import SimpleNamespace
        from idos.workers.base import WorkerStatus

        self.tickers.extend(context["tickers"])
        return SimpleNamespace(
            status=WorkerStatus.SUCCESS,
            output={"data": {
                ticker: {"merged_data": {
                    "asset_type": "etf",
                    "quote_currency": "USD",
                    "avg_dollar_volume_usd": self.dollar_volume,
                    "liquidity_provenance": {
                        "source": "yfinance", "as_of": "2026-10-16",
                        "currency": "USD", "basis": "UNDERLYING_USD_PROXY",
                    },
                    "market_data_normalization": {"status": "complete"},
                }}
                for ticker in context["tickers"]
            }},
        )


def test_momentum_score_requires_history():
    try:
        momentum_score([1.0] * 12)
    except ValueError:
        pass
    else:
        raise AssertionError("short history must be rejected")


def test_monthly_strategy_dry_run_does_not_persist(tmp_path: Path):
    worker = MonthlyStrategyWorker({"price_provider": FakePrices(), "market_gate_worker": FakeMarketGate()})
    result = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})
    assert result["strategy_id"] == "MOMENTUM_ETF"
    assert not (tmp_path / "idos-journal").exists()


def test_monthly_runner_uses_strategy_profile_not_a_fixed_strategy_id(tmp_path: Path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "strategies:\n"
        "  CUSTOM_MOMENTUM:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n"
        "    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n"
        "    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n"
        "    parameters:\n"
        "      universe: [QQQ]\n"
        "      select_top: 1\n"
        "      minimum_signal: 0.6\n"
        "      maximum_signal: 2.7\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: QQQ\n    type: etf\n",
        encoding="utf-8",
    )
    worker = MonthlyStrategyWorker({
        "strategy_id": "CUSTOM_MOMENTUM",
        "config_path": str(config_dir / "strategies.yml"),
        "price_provider": FakePrices(),
        "market_gate_worker": FakeMarketGate(),
    })

    output = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})

    assert output["strategy_id"] == "CUSTOM_MOMENTUM"
    assert output["candidate_tickers"] == ["QQQ"]


def test_monthly_strategy_excludes_etfs_below_global_liquidity_gate():
    gate = FakeMarketGate(dollar_volume=99_999)
    prices = FakePrices()
    worker = MonthlyStrategyWorker({"price_provider": prices, "market_gate_worker": gate})

    output = worker.run({"dry_run": True, "persist": False})

    assert gate.tickers
    assert output["market_gate"]["accepted_count"] == 0
    assert output["market_gate"]["rejected"]
    assert output["candidate_count"] == 0
    assert prices.tickers == []


def test_monthly_strategy_etfs_need_no_aum_or_market_cap():
    prices = FakePrices()
    worker = MonthlyStrategyWorker({"price_provider": prices, "market_gate_worker": FakeMarketGate()})
    output = worker.run({"dry_run": True, "persist": False, "candidate_tickers": ["QQQ"]})
    assert output["market_gate"]["accepted_count"] == 1
    assert output["market_gate"]["market_cap_applies_to"] == ["equity", "us_equity (legacy registry alias)"]
    assert "aum_min_usd" not in output["market_gate"]
    assert output["candidate_tickers"] == prices.tickers == ["QQQ"]


def test_monthly_strategy_persists_signal_in_sqlite(tmp_path: Path):
    worker = MonthlyStrategyWorker({"price_provider": FakePrices(), "market_gate_worker": FakeMarketGate()})
    worker.run({"base_path": str(tmp_path), "persist": True})
    from idos.data.sqlite import SQLiteStore
    store = SQLiteStore(tmp_path / "idos.db")
    rows = list(store.conn.execute("SELECT id FROM opportunities"))
    assert rows
    opp = store.get_opportunity(rows[0][0])
    assert opp["signal"]["momentum"] is not None
    assert opp["signal"]["quote_currency"] == "USD"
    assert opp["status"] == "SCREENED"


def test_monthly_rerun_preserves_reviewed_status(tmp_path: Path):
    from idos.data.sqlite import SQLiteStore

    worker = MonthlyStrategyWorker({"price_provider": FakePrices(), "market_gate_worker": FakeMarketGate()})
    worker.run({"base_path": str(tmp_path), "persist": True})
    store = SQLiteStore(tmp_path / "idos.db")
    opp_id = store.conn.execute("SELECT id FROM opportunities").fetchone()[0]
    opp = store.get_opportunity(opp_id)
    opp["status"] = "UNDER_RESEARCH"
    store.save_opportunity(opp)
    worker.run({"base_path": str(tmp_path), "persist": True})
    assert store.get_opportunity(opp_id)["status"] == "UNDER_RESEARCH"


def test_monthly_rerun_within_same_cycle_does_not_create_another_opportunity(tmp_path: Path):
    from idos.data.sqlite import SQLiteStore
    from idos.strategy.catalog import StrategyCatalog

    worker = MonthlyStrategyWorker({"price_provider": FakePrices(), "market_gate_worker": FakeMarketGate()})
    output = worker.run({
        "base_path": str(tmp_path), "dry_run": True, "persist": False,
        "candidate_tickers": ["QQQ"],
    })
    profile = StrategyCatalog(
        Path(__file__).resolve().parents[2] / "idos-config" / "strategies.yml"
    ).require("MOMENTUM_ETF")

    output["as_of_date"] = "2026-10-01"
    worker._persist(tmp_path, profile, output)
    output["as_of_date"] = "2026-10-19"
    output["generated_at"] = "2026-10-19T12:00:00-03:00"
    worker._persist(tmp_path, profile, output)

    store = SQLiteStore(tmp_path / "idos.db")
    rows = list(store.conn.execute("SELECT id FROM opportunities WHERE strategy_id = 'MOMENTUM_ETF'"))
    assert [row[0] for row in rows] == ["OPP-MOMENTUM-ETF-QQQ-0001"]


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
    worker = MonthlyStrategyWorker({
        "config_path": str(config_dir / "strategies.yml"),
        "price_provider": prices,
        "market_gate_worker": FakeMarketGate(),
    })

    output = worker.run({"base_path": str(tmp_path), "dry_run": True, "persist": False})

    assert prices.tickers == ["XLE"]
    assert output["candidate_tickers"] == ["XLE"]
    assert output["candidate_count"] == 1
    assert output["excluded_not_operable"] == ["QQQ"]
    assert output["market_gate"]["accepted_count"] == 1


def test_momentum_strategy_manual_subset_measures_coverage_for_applicable_tickers(tmp_path: Path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: MOMENTUM_ETF\nstrategies:\n"
        "  MOMENTUM_ETF:\n    enabled: true\n    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n    parameters:\n"
        "      universe: [QQQ, GLD]\n      supported_asset_types: [etf]\n      select_top: 2\n"
        "      minimum_signal: 0.6\n      maximum_signal: 2.7\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: QQQ\n    type: etf\n"
        "  - ticker: GLD\n    type: etf\n  - ticker: AAPL\n    type: us_equity\n",
        encoding="utf-8",
    )
    prices = FakePrices()
    worker = MonthlyStrategyWorker({
        "config_path": str(config_dir / "strategies.yml"),
        "price_provider": prices,
        "market_gate_worker": FakeMarketGate(),
    })

    output = worker.run({
        "base_path": str(tmp_path),
        "dry_run": True,
        "persist": False,
        "candidate_tickers": ["GLD", "AAPL"],
    })

    assert prices.tickers == ["GLD"]
    assert output["candidate_tickers"] == ["GLD"]
    assert output["run_scope"] == "bounded"
    assert output["requested_tickers"] == ["AAPL", "GLD"]
    assert output["candidate_count"] == 1
    assert output["eligible_universe_count"] == 2
    assert output["excluded_manual_tickers"] == ["AAPL"]
    assert output["market_gate"]["expected_count"] == 1
    assert output["market_gate"]["evaluated_count"] == 1
    assert output["market_gate"]["coverage_complete"] is True
    assert output["coverage_complete"] is True


def test_momentum_strategy_rejects_non_operable_manual_subset(tmp_path: Path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: MOMENTUM_ETF\nstrategies:\n"
        "  MOMENTUM_ETF:\n    enabled: true\n    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n    parameters:\n"
        "      universe: [QQQ]\n      select_top: 1\n"
        "      minimum_signal: 0.6\n      maximum_signal: 2.7\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: QQQ\n    type: etf\n",
        encoding="utf-8",
    )
    worker = MonthlyStrategyWorker({
        "config_path": str(config_dir / "strategies.yml"),
        "price_provider": FakePrices(),
        "market_gate_worker": FakeMarketGate(),
    })

    try:
        worker.run({"base_path": str(tmp_path), "candidate_tickers": ["AAPL"]})
    except ValueError as exc:
        assert "AAPL" in str(exc)
    else:
        raise AssertionError("non-operable test ticker must be rejected")


def test_monthly_strategy_persists_distinct_run_reports(tmp_path: Path):
    worker = MonthlyStrategyWorker({"price_provider": FakePrices(), "market_gate_worker": FakeMarketGate()})
    for _ in range(2):
        worker.run({"base_path": str(tmp_path), "persist": True})

    reports = list((tmp_path / "idos-journal" / "strategies" / "MOMENTUM_ETF").glob("*.yml"))
    assert len(reports) == 2
