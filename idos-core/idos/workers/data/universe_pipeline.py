import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from idos.workers.base import BaseWorker
from idos.workers.data.finviz_screener import FinvizScreenerScraper
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.pipeline_report import PipelineMetrics, PipelineReportGenerator
from idos.discovery.operability import OperabilityFilter
from idos.discovery.screening import FinvizScreener
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ

class UniversePipeline(BaseWorker):
    name = "universe_pipeline"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.journal_path = config.get("journal_path", "")
        self.config_path = config.get("config_path", "idos-config")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        metrics = PipelineMetrics()
        metrics.started_at = datetime.now(AR_TZ).isoformat()
        start_time = time.time()

        try:
            self._run_screener(metrics)
            self._run_filter(metrics)
            self._run_pre_score(metrics)
            self._run_fetch(metrics)
            self._run_scout(metrics)
            self._run_opportunity_creation(metrics)
            self._run_monthly_evaluation(metrics)
        except Exception as e:
            metrics.errors.append({"step": "pipeline", "error": str(e)})

        metrics.duration_seconds = time.time() - start_time
        metrics.finished_at = datetime.now(AR_TZ).isoformat()

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
        import yaml
        scoring_path = Path(self.config_path) / "scoring.yml"
        scout_min_score = 60
        if scoring_path.exists():
            scoring_data = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))
            scout_min_score = scoring_data.get("scoring", {}).get("min_opportunity_score", 60)
        print(f"[PIPELINE] Scout min_score: {scout_min_score}")

        scout_config = {
            "min_score": scout_min_score,
            "max_watchlist": self.config.get("max_watchlist", 300),
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

    def _run_opportunity_creation(self, metrics: PipelineMetrics):
        if not metrics.new_watchlist:
            return
        print(f"\n[PIPELINE] STEP 6: Opportunity Creation")

        import yaml
        scoring_path = Path(self.config_path) / "scoring.yml"
        min_score = 60
        if scoring_path.exists():
            scoring_data = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))
            min_score = scoring_data.get("scoring", {}).get("min_opportunity_score", 60)
        print(f"[PIPELINE] Min opportunity score: {min_score}")

        eligible = [e for e in metrics.new_watchlist if e.get("score", 0) >= min_score]
        metrics.opportunities_eligible = len(eligible)
        if not eligible:
            print(f"[PIPELINE] No tickers with score >= {min_score}")
            return

        journal_base = Path(self.journal_path) if self.journal_path else Path("idos-journal")
        existing = set()
        companies_dir = journal_base / "companies"
        if companies_dir.exists():
            for d in companies_dir.iterdir():
                if d.is_dir():
                    opp_dir = d / "case_file" / "opportunities"
                    if opp_dir.exists():
                        for opp in opp_dir.iterdir():
                            if opp.is_dir():
                                opp_file = opp / "opportunity.yml"
                                if opp_file.exists():
                                    try:
                                        raw = opp_file.read_text(encoding="utf-8")
                                        if "ticker:" in raw:
                                            for line in raw.splitlines():
                                                if line.strip().startswith("ticker:"):
                                                    existing.add(line.split(":", 1)[1].strip().strip("'\"").upper())
                                                    break
                                    except Exception:
                                        pass

        from idos.models.enums import OpportunityStatus
        from idos.models.journal import Opportunity
        from idos.models.conviction import Conviction

        created = 0
        date_prefix = datetime.now(AR_TZ).strftime('%Y%m%d')
        seq = 1
        for entry in eligible:
            ticker = entry["ticker"].upper()
            if ticker in existing:
                metrics.opportunities_existing += 1
                continue

            opp_id = f"OPP-{date_prefix}-{seq:03d}"
            seq += 1
            opp = Opportunity(
                id=opp_id,
                ticker=ticker,
                status=OpportunityStatus.SCREENED,
                conviction=Conviction(overall=entry.get("score", 0)),
            )
            opp_data = opp.model_dump(mode="json")
            opp_dir = journal_base / "companies" / ticker / "case_file" / "opportunities" / opp_id
            opp_dir.mkdir(parents=True, exist_ok=True)
            opp_file = opp_dir / "opportunity.yml"
            with open(opp_file, "w", encoding="utf-8") as f:
                yaml.dump(opp_data, f, default_flow_style=False, allow_unicode=True)
            existing.add(ticker)
            created += 1

        metrics.opportunities_created = created
        print(f"[PIPELINE] Opportunities: {created} created, {metrics.opportunities_existing} existing, {len(eligible)} eligible")

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
        cache = DataCache()
        data = cache.get(f"merged:{ticker}")
        if data:
            return data.get("merged_data", data)
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

    def _run_monthly_evaluation(self, metrics: PipelineMetrics):
        """Evalúa oportunidades existentes: score < threshold → WATCHLIST, score >= threshold en WATCHLIST → SCREENED."""
        from idos.models.enums import OpportunityStatus
        from idos.data.journal import JournalRepository

        print("\n[PIPELINE] STEP 7: Monthly Evaluation")
        journal = JournalRepository(Path(self.journal_path)) if self.journal_path else None
        companies_dir = Path(self.journal_path or "idos-journal") / "companies"
        if not companies_dir.exists():
            return

        import yaml
        scoring_path = Path(self.config_path) / "scoring.yml"
        min_score = 60
        if scoring_path.exists():
            scoring_data = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))
            min_score = scoring_data.get("scoring", {}).get("min_opportunity_score", 60)

        downgraded = 0
        upgraded = 0
        unchanged = 0
        skipped_no_data = 0

        scout_by_ticker = {e.get("ticker", "").upper(): e for e in metrics.new_watchlist}

        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name.upper()
            opp_dir = d / "case_file" / "opportunities"
            if not opp_dir.exists():
                continue

            scout_result = scout_by_ticker.get(ticker)
            ticker_in_universe = scout_result is not None

            for opp in sorted(opp_dir.iterdir()):
                if not opp.is_dir():
                    continue
                yf = opp / "opportunity.yml"
                if not yf.exists():
                    continue
                try:
                    data = yaml.safe_load(yf.read_text(encoding="utf-8"))
                    if not data:
                        continue
                    current_status = data.get("status", "")

                    if not ticker_in_universe:
                        if current_status in ("SCREENED", "UNDER_RESEARCH", "WATCHLIST"):
                            skipped_no_data += 1
                        continue

                    score = scout_result.get("score", 0)
                    opp_id = data.get("id", opp.name)

                    if current_status == "WATCHLIST":
                        if score >= min_score:
                            data["status"] = "SCREENED"
                            data["updated_at"] = datetime.now(AR_TZ).strftime("%Y-%m-%dT%H:%M:%S")
                            yf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
                            if journal:
                                journal.save_opportunity(ticker, data)
                            upgraded += 1
                            print(f"  {ticker}: WATCHLIST -> SCREENED (score={score})")
                        else:
                            unchanged += 1
                    elif current_status in ("SCREENED", "UNDER_RESEARCH"):
                        if score < min_score:
                            data["status"] = "WATCHLIST"
                            data["updated_at"] = datetime.now(AR_TZ).strftime("%Y-%m-%dT%H:%M:%S")
                            yf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
                            if journal:
                                journal.save_opportunity(ticker, data)
                            downgraded += 1
                            print(f"  {ticker}: {current_status} -> WATCHLIST (score={score} < {min_score})")
                        else:
                            unchanged += 1
                    else:
                        unchanged += 1
                except Exception as e:
                    metrics.errors.append({"step": "monthly_evaluation", "ticker": ticker, "error": str(e)})

        metrics.downgraded_to_watchlist = downgraded
        metrics.upgraded_to_screened = upgraded
        print(f"[PIPELINE] Monthly Evaluation: {upgraded} upgraded to SCREENED, {downgraded} downgraded to WATCHLIST, {unchanged} unchanged, {skipped_no_data} skipped (not in universe)")

    def _load_screener_config(self) -> dict:
        import yaml
        config_path = Path(self.config_path) / "finviz_screener.yml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            return data.get("screener", {})
        return {}