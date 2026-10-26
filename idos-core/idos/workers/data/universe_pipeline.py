import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.pipeline_report import PipelineMetrics, PipelineReportGenerator
from idos.discovery.operability import OperabilityFilter
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ
from idos.strategy.catalog import StrategyCatalog
from idos.market.liquidity import MarketDataSettings, supports_asset_type

class UniversePipeline(BaseWorker):
    name = "universe_pipeline"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.journal_path = config.get("journal_path", "")
        self.config_path = config.get("config_path", "idos-config")
        self.strategy_id = str(config.get("strategy_id", "COMPOUNDER")).upper()
        self.strategy_catalog = StrategyCatalog(Path(self.config_path) / "strategies.yml")
        self.strategy = self.strategy_catalog.get(self.strategy_id)
        if not self.strategy.enabled:
            raise ValueError(f"Strategy is disabled: {self.strategy_id}")
        if self.strategy.discovery_profile not in {"compounder", "multibaggers"}:
            raise ValueError(f"UniversePipeline has no runner for discovery profile: {self.strategy.discovery_profile}")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        if self.strategy.discovery_profile == "multibaggers":
            from idos.discovery.multibaggers_pipeline import MultibaggersPipeline
            return MultibaggersPipeline(self.config).run(context)
        metrics = PipelineMetrics()
        metrics.started_at = datetime.now(AR_TZ).isoformat()
        start_time = time.time()

        try:
            self._load_candidate_universe(metrics, context.get("candidate_tickers"))
            if not metrics.errors:
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

        if metrics.errors:
            details = "; ".join(
                f"{error.get('step', 'pipeline')}: {error.get('error', 'unknown error')}"
                for error in metrics.errors
            )
            return WorkerResult(
                status=WorkerStatus.FAILED,
                worker=self.name,
                output=metrics.to_dict(),
                error=details,
            )

        if metrics.candidate_count == 0:
            if context.get("candidate_tickers"):
                return {
                    "status": "skipped",
                    "reason": "no_requested_candidates_match_strategy_asset_types",
                    "candidate_source": metrics.candidate_source,
                    "requested_tickers": context["candidate_tickers"],
                    "candidate_count": 0,
                    "candidate_tickers": [],
                }
            message = "The operable universe contains zero candidates; refusing to report a successful empty universe run."
            return WorkerResult(
                status=WorkerStatus.FAILED,
                worker=self.name,
                output=metrics.to_dict(),
                error=message,
            )

        return metrics.to_dict()

    def _load_candidate_universe(self, metrics: PipelineMetrics, requested_tickers=None):
        print("\n[PIPELINE] STEP 1: Operable Candidate Universe")
        operable_path = str(Path(self.config_path) / "universe/operable.yml")
        operable = OperabilityFilter(operable_path)
        metrics.candidate_source = operable_path
        all_tickers = operable.tickers
        supported_types = set(self.strategy.parameters.get("supported_asset_types", []))
        if requested_tickers:
            try:
                requested = operable.validate_selection(requested_tickers)
            except ValueError as exc:
                metrics.errors.append({
                    "step": "candidate_universe",
                    "error": str(exc),
                })
                metrics.candidate_tickers = []
                return
            metrics.candidate_tickers = requested
        else:
            metrics.candidate_tickers = sorted(all_tickers)
        if supported_types:
            entries_by_ticker = {entry["ticker"]: entry for entry in operable.list()}
            metrics.candidate_tickers = [
                ticker for ticker in metrics.candidate_tickers
                if supports_asset_type(entries_by_ticker.get(ticker, {}).get("type"), supported_types)
            ]
        metrics.candidate_count = len(metrics.candidate_tickers)
        if not metrics.candidate_tickers and not requested_tickers:
            metrics.errors.append({
                "step": "candidate_universe",
                "error": f"No operable candidates found in {operable_path}",
            })
        print(
            f"[PIPELINE] Candidate universe: {metrics.candidate_count} tickers "
            f"from {operable_path}"
        )

    def _run_filter(self, metrics: PipelineMetrics):
        print("\n[PIPELINE] STEP 2: Operable Filter")
        # The candidate source is the operable registry itself. Keep this metric
        # for report compatibility and make the invariant explicit here.
        metrics.operable_count = len(metrics.candidate_tickers)
        metrics.operable_filtered = 0
        tickers = metrics.candidate_tickers
        print(f"[PIPELINE] Operable: {metrics.operable_count} tickers ({metrics.operable_filtered} filtered)")

    def _run_pre_score(self, metrics: PipelineMetrics):
        if not metrics.candidate_tickers:
            return
        # Strategy predicates run once, after fresh market/financial data.
        metrics.pre_score_count = len(metrics.candidate_tickers)

    def _run_fetch(self, metrics: PipelineMetrics):
        if not metrics.candidate_tickers:
            return
        print(f"\n[PIPELINE] STEP 4: Data Fetch ({len(metrics.candidate_tickers)} tickers)")
        cache_path = Path(self.config.get("cache_path", "cache"))
        to_fetch = []
        valid_cached = []
        for ticker in metrics.candidate_tickers:
            data = self._get_cached_data(cache_path, ticker)
            if data and DataRefreshWorker._has_normalized_market_gates(data):
                metrics.fetch_cached += 1
                valid_cached.append(ticker)
            else:
                to_fetch.append(ticker)

        if not to_fetch:
            print(f"[PIPELINE] All {metrics.fetch_cached} tickers already cached")
            return

        print(f"[PIPELINE] Fetching {len(to_fetch)} new tickers...")
        max_workers = self.config.get("max_fetch_workers", 5)
        worker_local = threading.local()
        valid_fetched = []

        def fetch_one(ticker):
            # Each DataRefreshWorker owns a SQLiteStore connection. Construct it
            # in the worker thread and reuse it only on that same thread.
            if not hasattr(worker_local, "refresher"):
                worker_local.refresher = DataRefreshWorker(self.config)
            return ticker, worker_local.refresher.execute({"tickers": [ticker]})

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in to_fetch}
            done = 0
            for future in as_completed(futures):
                ticker, result = future.result()
                done += 1
                output = result.output or {}
                fetched_data = (output.get("data") or {}).get(ticker, {})
                merged_data = fetched_data.get("merged_data", fetched_data) if isinstance(fetched_data, dict) else {}
                nested_errors = output.get("errors") or []
                if result.status == WorkerStatus.FAILED or not merged_data:
                    detail = result.error or (nested_errors[0] if nested_errors else "no validated merged data")
                    metrics.fetch_errors.append({"ticker": ticker, "error": result.error})
                    if metrics.fetch_errors[-1]["error"] is None:
                        metrics.fetch_errors[-1]["error"] = str(detail)
                else:
                    metrics.fetch_new += 1
                    valid_fetched.append(ticker)
                    if nested_errors:
                        metrics.fetch_errors.extend(
                            {"ticker": ticker, "error": str(error)} for error in nested_errors
                        )
                if done % 25 == 0:
                    print(f"[PIPELINE] Fetch: {done}/{len(to_fetch)} done")

        print(f"[PIPELINE] Fetch: {metrics.fetch_new} new, {metrics.fetch_cached} cached, {len(metrics.fetch_errors)} errors")
        metrics.candidate_tickers = valid_cached + valid_fetched
        if not metrics.candidate_tickers:
            metrics.errors.append({
                "step": "data_quality",
                "error": "No candidate produced validated merged market data; refusing to score or create opportunities.",
            })

    def _run_scout(self, metrics: PipelineMetrics):
        if not metrics.candidate_tickers:
            return
        print(f"\n[PIPELINE] STEP 5: Scout ({len(metrics.candidate_tickers)} tickers)")
        from idos.discovery.configured_scout import configured_scout
        scout = configured_scout(self.config_path, self.strategy_id)
        scout_config = {"max_watchlist": self.config.get("max_watchlist", 300)}
        watchlist = WatchlistManager(max_entries=scout_config["max_watchlist"])
        if self.journal_path:
            watchlist.restore(JournalRepository(Path(self.journal_path)).load_watchlist())
        ranking = RankingSystem()
        cache_path = Path(self.config.get("cache_path", "cache"))

        screened = []
        quality_rejections = 0
        for ticker in metrics.candidate_tickers:
            data = self._get_cached_data(cache_path, ticker)
            result = self._score_ticker(scout, ticker, data)
            metrics.scout_evaluations.append(result)
            if result["passed"]:
                metrics.scout_passed += 1
                watchlist.add(ticker=ticker, score=result["score"], reason=result["reason"])
            else:
                watchlist.remove(ticker)
                metrics.scout_rejected += 1
                if not result.get("data_quality_valid", True):
                    metrics.scout_data_quality_rejected += 1
                    metrics.scout_data_quality_details.append({
                        "ticker": ticker,
                        "missing_critical_metrics": result.get("missing_critical_metrics", []),
                        "conflicting_critical_metrics": result.get("conflicting_metrics", []),
                    })
                    quality_rejections += 1
            screened.append(result)

        ranked = ranking.rank(screened)
        metrics.new_watchlist = [
            {"ticker": r.ticker, "score": r.scout_score, "rank": r.rank, "passed": True}
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
        if not metrics.new_watchlist and not metrics.scout_evaluations:
            return
        print(f"\n[PIPELINE] STEP 6: Opportunity Creation")

        import yaml
        # new_watchlist contains only candidates passing every profile predicate.
        eligible = metrics.new_watchlist
        metrics.opportunities_eligible = len(eligible)
        evaluations_by_ticker = {
            str(result.get("ticker", "")).upper(): result
            for result in metrics.scout_evaluations
            if result.get("ticker")
        }

        journal_base = Path(self.journal_path) if self.journal_path else Path("idos-journal")
        existing = set()
        existing_paths: dict[tuple[str, str], list[Path]] = {}
        opportunity_history: dict[tuple[str, str], list[dict[str, Any]]] = {}
        from idos.models.opportunity_identity import is_active_opportunity
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
                                        raw = yaml.safe_load(opp_file.read_text(encoding="utf-8")) or {}
                                        existing_ticker = str(raw.get("ticker", d.name)).upper()
                                        existing_strategy = str(raw.get("strategy_id", "COMPOUNDER")).upper()
                                        key = (existing_ticker, existing_strategy)
                                        opportunity_history.setdefault(key, []).append(raw)
                                        if is_active_opportunity(raw):
                                            existing.add(key)
                                            existing_paths.setdefault(key, []).append(opp_file)
                                    except Exception:
                                        pass

        # Record a failed current screen on existing cases without changing
        # their lifecycle or any attributed manager decision.
        for result in metrics.scout_evaluations:
            if str(result.get("status", "")).upper() == "PASSED":
                continue
            ticker = str(result.get("ticker", "")).upper()
            paths = existing_paths.get((ticker, self.strategy_id), [])
            if not paths:
                continue
            evidence = self._build_discovery_evidence(ticker, result)
            for opp_file in paths:
                try:
                    existing_data = yaml.safe_load(opp_file.read_text(encoding="utf-8")) or {}
                    existing_data["latest_discovery_evidence"] = evidence
                    existing_data["discovery_last_evaluated_at"] = evidence["evaluated_at"]
                    opp_file.write_text(
                        yaml.dump(existing_data, default_flow_style=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                    metrics.opportunities_discovery_review += 1
                except (OSError, yaml.YAMLError) as exc:
                    metrics.errors.append({
                        "step": "opportunity_discovery_evidence",
                        "ticker": ticker,
                        "error": str(exc),
                    })

        from idos.models.enums import OpportunityStatus
        from idos.models.journal import Opportunity
        from idos.models.conviction import Conviction

        from idos.models.opportunity_identity import build_opportunity_id, next_opportunity_cycle

        created = 0
        for entry in eligible:
            ticker = entry["ticker"].upper()
            key = (ticker, self.strategy_id)
            if key in existing:
                metrics.opportunities_existing += 1
                evidence = self._build_discovery_evidence(
                    ticker, evaluations_by_ticker.get(ticker)
                )
                for opp_file in existing_paths.get(key, []):
                    try:
                        existing_data = yaml.safe_load(opp_file.read_text(encoding="utf-8")) or {}
                        existing_data["latest_discovery_evidence"] = evidence
                        existing_data["discovery_last_evaluated_at"] = evidence["evaluated_at"]
                        opp_file.write_text(
                            yaml.dump(existing_data, default_flow_style=False, allow_unicode=True),
                            encoding="utf-8",
                        )
                    except (OSError, yaml.YAMLError) as exc:
                        metrics.errors.append({
                            "step": "opportunity_discovery_evidence",
                            "ticker": ticker,
                            "error": str(exc),
                        })
                continue

            cycle = next_opportunity_cycle(
                opportunity_history.get(key, []), self.strategy_id, ticker
            )
            opp_id = build_opportunity_id(self.strategy_id, ticker, cycle)
            opp = Opportunity(
                id=opp_id,
                ticker=ticker,
                status=OpportunityStatus.SCREENED,
                strategy_id=self.strategy.strategy_id,
                strategy_version=self.strategy.parameters["scout"]["version"],
                core=self.strategy.core,
                sleeve=self.strategy.sleeve,
                thesis_type=self.strategy.thesis_type,
                entry_policy=self.strategy.entry_policy,
                research_profile=self.strategy.research_profile,
                origin="automated",
                conviction=Conviction(overall=0),
            )
            opp_data = opp.model_dump(mode="json")
            opp_data["opportunity_cycle"] = cycle
            opp_data["discovery_evidence"] = self._build_discovery_evidence(
                ticker, evaluations_by_ticker.get(ticker)
            )
            opp_dir = journal_base / "companies" / ticker / "case_file" / "opportunities" / opp_id
            opp_dir.mkdir(parents=True, exist_ok=True)
            opp_file = opp_dir / "opportunity.yml"
            with open(opp_file, "w", encoding="utf-8") as f:
                yaml.dump(opp_data, f, default_flow_style=False, allow_unicode=True)
            existing.add((ticker, self.strategy_id))
            opportunity_history.setdefault(key, []).append(opp_data)
            created += 1

        metrics.opportunities_created = created
        print(f"[PIPELINE] Opportunities: {created} created, {metrics.opportunities_existing} existing, {len(eligible)} eligible")

    def _build_discovery_evidence(
        self, ticker: str, scout_result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        cached = self._get_cached_data(Path(self.config.get("cache_path", "cache")), ticker)
        fields = [rule["metric"] for rule in self.strategy.parameters["scout"]["filters"]]
        result = scout_result or {}
        evidence = {
            "policy": self.strategy.parameters["scout"],
            "eligibility_status": str(result.get("status", "PASSED")).upper(),
            "evaluated_at": datetime.now(AR_TZ).isoformat(),
            "metrics": {key: cached.get(key) for key in fields},
            "reason": result.get("reason"),
            "missing_metrics": result.get("missing_critical_metrics", []),
            "conflicting_metrics": result.get("conflicting_metrics", []),
            "filter_results": result.get("details", {}),
            "financial_observations": cached.get("financial_observations", {}),
            "market_data_normalization": cached.get("market_data_normalization", {}),
            "liquidity_provenance": cached.get("liquidity_provenance", {}),
            "market_cap_provenance": cached.get("market_cap_provenance", {}),
            "data_provenance": cached.get("data_provenance", {}),
        }
        market_quote = self._latest_market_quote(cached)
        if market_quote:
            evidence["market_quote"] = market_quote
        return evidence

    @staticmethod
    def _latest_market_quote(cached: dict[str, Any]) -> dict[str, Any] | None:
        """Keep one dated public quote in the opportunity for later workflows."""
        prices = cached.get("price_history")
        dates = cached.get("price_history_dates")
        if not isinstance(prices, list) or not isinstance(dates, list) or len(prices) != len(dates):
            return None
        for price, quote_date in reversed(list(zip(prices, dates))):
            if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
                continue
            if not isinstance(quote_date, str):
                continue
            try:
                if datetime.fromisoformat(quote_date).date().isoformat() != quote_date:
                    continue
            except ValueError:
                continue
            provenance = cached.get("data_provenance")
            field_sources = provenance.get("field_sources", {}) if isinstance(provenance, dict) else {}
            sources = field_sources.get("price_history", []) if isinstance(field_sources, dict) else []
            source = ", ".join(sorted({str(item) for item in sources if item})) if isinstance(sources, list) else ""
            currency = cached.get("quote_currency") or cached.get("currency")
            valid_currency = (
                isinstance(currency, str) and len(currency) == 3
                and currency.isalpha() and currency == currency.upper()
            )
            if not source or not valid_currency:
                return None
            return {
                "price": float(price),
                "as_of_date": quote_date,
                "currency": currency,
                "source": source,
            }
        return None

    def _score_ticker(self, scout: ScoutEngine, ticker: str, data: dict) -> dict:
        from idos.discovery.configured_scout import configured_scout
        scout = scout or configured_scout(self.config_path, self.strategy_id)
        result = scout.scan_market_data(ticker, data)
        return {
            "ticker": ticker, "score": result.score, "scout_score": result.score,
            "passed": result.passed, "status": result.status,
            "data_quality_valid": result.status != "PENDING_DATA",
            "missing_critical_metrics": result.missing_metrics,
            "conflicting_metrics": result.conflicting_metrics,
            "policy_version": result.policy_version,
            "details": result.details, "reason": result.reason,
        }

    def _get_cached_data(self, cache_path: Path, ticker: str) -> dict:
        cache = DataCache()
        data = cache.get(f"merged:{ticker}")
        if data:
            return DataRefreshWorker._cache_file_payload(data)
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
        """Re-evalúa elegibilidad con los filtros financieros vigentes del perfil."""
        from idos.models.enums import OpportunityStatus
        from idos.data.journal import JournalRepository

        print("\n[PIPELINE] STEP 7: Monthly Evaluation")
        journal = JournalRepository(Path(self.journal_path)) if self.journal_path else None
        companies_dir = Path(self.journal_path or "idos-journal") / "companies"
        if not companies_dir.exists():
            return

        import yaml
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

                    eligible = scout_result.get("passed", False)
                    opp_id = data.get("id", opp.name)

                    if current_status == "WATCHLIST":
                        if eligible:
                            data["status"] = "SCREENED"
                            data["updated_at"] = datetime.now(AR_TZ).strftime("%Y-%m-%dT%H:%M:%S")
                            yf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
                            if journal:
                                journal.save_opportunity(ticker, data)
                            upgraded += 1
                            print(f"  {ticker}: WATCHLIST -> SCREENED (configured Scout filters passed)")
                        else:
                            unchanged += 1
                    elif current_status in ("SCREENED", "UNDER_RESEARCH"):
                        if not eligible:
                            data["status"] = "WATCHLIST"
                            data["updated_at"] = datetime.now(AR_TZ).strftime("%Y-%m-%dT%H:%M:%S")
                            yf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
                            if journal:
                                journal.save_opportunity(ticker, data)
                            downgraded += 1
                            print(f"  {ticker}: {current_status} -> WATCHLIST (configured Scout filters failed)")
                        else:
                            unchanged += 1
                    else:
                        unchanged += 1
                except Exception as e:
                    metrics.errors.append({"step": "monthly_evaluation", "ticker": ticker, "error": str(e)})

        metrics.downgraded_to_watchlist = downgraded
        metrics.upgraded_to_screened = upgraded
        print(f"[PIPELINE] Monthly Evaluation: {upgraded} upgraded to SCREENED, {downgraded} downgraded to WATCHLIST, {unchanged} unchanged, {skipped_no_data} skipped (not in universe)")
