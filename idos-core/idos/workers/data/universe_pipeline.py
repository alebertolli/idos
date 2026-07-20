import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from idos.workers.base import BaseWorker
from idos.workers.data.finviz_screener import FinvizScreenerScraper
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.pipeline_report import PipelineMetrics, PipelineReportGenerator
from idos.discovery.operability import OperabilityFilter
from idos.discovery.screening import FinvizScreener
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.data.journal import JournalRepository


class UniversePipeline(BaseWorker):
    name = "universe_pipeline"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.journal_path = config.get("journal_path", "")
        self.config_path = config.get("config_path", "idos-config")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        metrics = PipelineMetrics()
        metrics.started_at = datetime.now(UTC).isoformat()
        start_time = time.time()

        try:
            self._run_screener(metrics)
            self._run_filter(metrics)
            self._run_pre_score(metrics)
            self._run_fetch(metrics)
            self._run_scout(metrics)
        except Exception as e:
            metrics.errors.append({"step": "pipeline", "error": str(e)})

        metrics.duration_seconds = time.time() - start_time
        metrics.finished_at = datetime.now(UTC).isoformat()

        report = PipelineReportGenerator()
        report_text = report.generate(metrics)
        report_path = report.save(report_text, self.journal_path)
        print(f"\n[PIPELINE] Report saved: {report_path}")
        print(report_text)

        self._send_notification(report_text)

        return metrics.to_dict()

    def _run_screener(self, metrics: PipelineMetrics):
        print("\n[PIPELINE] STEP 1: Finviz Screener")
        screener_config = self._load_screener_config()
        scraper = FinvizScreenerScraper(screener_config)
        result = scraper.execute({})
        if result.status == "failed":
            metrics.errors.append({"step": "finviz", "error": result.error})
            return
        tickers = result.output.get("tickers", [])
        metrics.finviz_count = len(tickers)
        metrics.finviz_from_cache = result.output.get("from_cache", False)
        metrics.finviz_tickers = [t.get("ticker", "") for t in tickers]
        print(f"[PIPELINE] Finviz: {metrics.finviz_count} tickers (cache: {metrics.finviz_from_cache})")

    def _run_filter(self, metrics: PipelineMetrics):
        print("\n[PIPELINE] STEP 2: Operable Filter")
        operable_path = str(Path(self.config_path) / "universe/operable.yml")
        operable = OperabilityFilter(operable_path)
        before = metrics.finviz_count
        tickers = [t for t in metrics.finviz_tickers if operable.is_operable(t)]
        metrics.operable_count = len(tickers)
        metrics.operable_filtered = before - len(tickers)
        metrics.finviz_tickers = tickers
        print(f"[PIPELINE] Operable: {metrics.operable_count} tickers ({metrics.operable_filtered} filtered)")

    def _run_pre_score(self, metrics: PipelineMetrics):
        if not metrics.finviz_tickers:
            return
        print("\n[PIPELINE] STEP 3: Pre-Scoring")
        screener_dir = str(Path(self.config_path) / "screeners")
        screener = FinvizScreener(screener_dir)
        cache_path = Path(self.config.get("cache_path", "cache"))
        passed = []
        for ticker in metrics.finviz_tickers:
            data = self._get_cached_data(cache_path, ticker)
            if not data:
                passed.append(ticker)
                continue
            results = screener.run_all(data)
            if any(results.values()):
                passed.append(ticker)
            else:
                metrics.pre_score_rejected += 1
        metrics.pre_score_count = len(passed)
        metrics.finviz_tickers = passed
        print(f"[PIPELINE] Pre-Score: {metrics.pre_score_count} passed, {metrics.pre_score_rejected} rejected")

    def _run_fetch(self, metrics: PipelineMetrics):
        if not metrics.finviz_tickers:
            return
        print(f"\n[PIPELINE] STEP 4: Data Fetch ({len(metrics.finviz_tickers)} tickers)")
        cache_path = Path(self.config.get("cache_path", "cache"))
        to_fetch = []
        for ticker in metrics.finviz_tickers:
            data = self._get_cached_data(cache_path, ticker)
            if data:
                metrics.fetch_cached += 1
            else:
                to_fetch.append(ticker)

        if not to_fetch:
            print(f"[PIPELINE] All {metrics.fetch_cached} tickers already cached")
            return

        print(f"[PIPELINE] Fetching {len(to_fetch)} new tickers...")
        max_workers = self.config.get("max_fetch_workers", 5)
        refresher = DataRefreshWorker(self.config)

        def fetch_one(ticker):
            return ticker, refresher.execute({"tickers": [ticker]})

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in to_fetch}
            done = 0
            for future in as_completed(futures):
                ticker, result = future.result()
                done += 1
                if result.status == "failed":
                    metrics.fetch_errors.append({"ticker": ticker, "error": result.error})
                else:
                    metrics.fetch_new += 1
                if done % 25 == 0:
                    print(f"[PIPELINE] Fetch: {done}/{len(to_fetch)} done")

        print(f"[PIPELINE] Fetch: {metrics.fetch_new} new, {metrics.fetch_cached} cached, {len(metrics.fetch_errors)} errors")

    def _run_scout(self, metrics: PipelineMetrics):
        if not metrics.finviz_tickers:
            return
        print(f"\n[PIPELINE] STEP 5: Scout ({len(metrics.finviz_tickers)} tickers)")
        scout_config = {
            "min_score": self.config.get("min_scout_score", 50),
            "max_watchlist": self.config.get("max_watchlist", 50),
            "screeners_dir": str(Path(self.config_path) / "screeners"),
            "operable_path": str(Path(self.config_path) / "universe/operable.yml"),
            "journal_path": self.journal_path,
            "cache_path": self.config.get("cache_path", "cache"),
        }
        scout = ScoutEngine(min_score=scout_config["min_score"])
        watchlist = WatchlistManager(max_entries=scout_config["max_watchlist"])
        ranking = RankingSystem()
        cache_path = Path(self.config.get("cache_path", "cache"))

        screened = []
        for ticker in metrics.finviz_tickers:
            data = self._get_cached_data(cache_path, ticker)
            result = self._score_ticker(scout, ticker, data)
            if result["passed"]:
                metrics.scout_passed += 1
                watchlist.add(ticker=ticker, score=result["score"], reason=result["reason"])
            else:
                metrics.scout_rejected += 1
            screened.append(result)

        ranked = ranking.rank(screened)
        metrics.new_watchlist = [
            {"ticker": r.ticker, "score": r.scout_score, "rank": r.rank}
            for r in ranked if r.ticker in {s["ticker"] for s in screened if s["passed"]}
        ]

        if self.journal_path:
            self._save_watchlist(watchlist)

        print(f"[PIPELINE] Scout: {metrics.scout_passed} passed, {metrics.scout_rejected} rejected")
        if metrics.new_watchlist:
            print(f"[PIPELINE] Top watchlist:")
            for entry in metrics.new_watchlist[:5]:
                print(f"  {entry['ticker']}: score={entry['score']} rank={entry['rank']}")

    def _score_ticker(self, scout: ScoutEngine, ticker: str, data: dict) -> dict:
        def _num(v, default=0.0):
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v.replace(",", "").replace("$", "").replace("%", ""))
                except (ValueError, TypeError):
                    pass
            return default

        metrics = {
            "market_cap": _num(data.get("market_cap")),
            "avg_volume": _num(data.get("volume_avg")) or _num(data.get("avg_volume")),
            "pe_ratio": _num(data.get("pe_ratio_ttm")) or _num(data.get("pe_ratio")),
            "ev_ebitda": _num(data.get("ev_ebitda")),
            "roic": _num(data.get("roic_pct")),
            "operating_margin": _num(data.get("operating_margin_pct")),
            "debt_to_equity": _num(data.get("debt_equity_ratio")),
            "revenue_growth": _num(data.get("revenue_growth_pct")),
        }
        result = scout.scan(ticker=ticker, data={"metrics": metrics})
        return {
            "ticker": ticker,
            "score": result.score,
            "scout_score": result.score,
            "passed": result.passed,
            "details": result.details,
            "reason": result.reason,
        }

    def _get_cached_data(self, cache_path: Path, ticker: str) -> dict:
        import json
        cache_file = cache_path / f"{ticker}.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_watchlist(self, watchlist: WatchlistManager):
        journal = Path(self.journal_path)
        (journal / "portfolio").mkdir(parents=True, exist_ok=True)
        repo = JournalRepository(journal)
        entries = [
            {
                "ticker": e.ticker,
                "score": e.score,
                "reason": e.reason,
                "added_at": e.added_at,
                "alerts": e.alerts,
                "notified": e.notified,
            }
            for e in watchlist.entries
        ]
        repo.save_watchlist(entries)

    def _send_notification(self, report: str):
        telegram_token = self.config.get("telegram_token") or ""
        telegram_chat = self.config.get("telegram_chat_id") or ""
        if not telegram_token or not telegram_chat:
            return
        try:
            from idos.workers.notifications.telegram import TelegramNotifier
            notifier = TelegramNotifier({
                "bot_token": telegram_token,
                "chat_id": telegram_chat,
            })
            notifier.execute({"message": report, "parse_mode": "Markdown"})
        except Exception as e:
            print(f"[PIPELINE] Notification failed: {e}")

    def _load_screener_config(self) -> dict:
        import yaml
        config_path = Path(self.config_path) / "finviz_screener.yml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            return data.get("screener", {})
        return {}