from pathlib import Path

from idos.resilience.error_manager import (
    ErrorManager,
    CATEGORY_DATOS,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)
from idos.workers.automation.data_error_reporter import build_issue_body, consolidate_errors


class TestErrorManager:
    def test_report_and_load(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        rec = em.report(category=CATEGORY_DATOS, severity=SEVERITY_HIGH,
                        ticker="AAPL", message="yfinance fallo")
        assert rec.ticker == "AAPL"
        assert rec.severity == SEVERITY_HIGH
        assert (tmp_path / "cache" / "data_errors.json").exists()
        errors = em.errors_since(days=1)
        assert len(errors) == 1

    def test_dedup_by_day_same_signature(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="MSFT", message="stockanalysis fallo")
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="MSFT", message="stockanalysis fallo")
        assert len(em.errors_since(days=1)) == 1

    def test_higher_severity_wins(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_LOW,
                  ticker="MSFT", message="degradacion de fuente")
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_HIGH,
                  ticker="MSFT", message="degradacion de fuente")
        errors = em.errors_since(days=1)
        assert len(errors) == 1
        assert errors[0].severity == SEVERITY_HIGH

    def test_mark_reported(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="TSLA", message="error x")
        assert em.pending_reported() is False
        em.mark_reported()
        assert em.pending_reported() is True
        assert consolidate_errors(tmp_path) == []

    def test_different_tickers_not_deduped(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="AAPL", message="fallo")
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="MSFT", message="fallo")
        assert len(em.errors_since(days=1)) == 2


class TestDataErrorReporter:
    def test_build_issue_body_contains_tickers(self):
        errors = [
            {"ticker": "AAPL", "severity": "alta", "category": "datos", "message": "fallo"},
            {"ticker": "MSFT", "severity": "baja", "category": "datos", "message": "degradacion"},
        ]
        body = build_issue_body(errors, run_url="https://x")
        assert "AAPL" in body
        assert "MSFT" in body
        assert "https://x" in body

    def test_consolidate_returns_only_unreported(self, tmp_path: Path):
        em = ErrorManager(tmp_path)
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM,
                  ticker="AAPL", message="fallo")
        em.mark_reported()
        em.report(category=CATEGORY_DATOS, severity=SEVERITY_HIGH,
                  ticker="NFLX", message="nuevo fallo")
        pending = consolidate_errors(tmp_path)
        assert len(pending) == 1
        assert pending[0]["ticker"] == "NFLX"
