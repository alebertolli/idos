from pathlib import Path

from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker, momentum_score


class FakePrices:
    def get_history(self, ticker, period="2y", interval="1mo"):
        return [{"date": f"2026-{(i % 12) + 1:02d}-01", "close": 100 + i, "volume": 1} for i in range(24)]


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
