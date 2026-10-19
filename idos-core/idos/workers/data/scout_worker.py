import re
from pathlib import Path
from typing import Any

from idos.discovery.scout import ScoutEngine, ScoutResult
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.discovery.operability import OperabilityFilter
from idos.discovery.screening import FinvizScreener
from idos.workers.base import BaseWorker
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.cache import DataCache
from idos.data.journal import JournalRepository
from idos.market.liquidity import MarketDataSettings


class ScoutWorker(BaseWorker):
    name = "scout_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.universe_path = config.get("universe_path", "")
        from idos.discovery.configured_scout import configured_scout, resolve_config_directory
        config_path = resolve_config_directory(config.get("config_path", "idos-config"))
        self.scout_engine = configured_scout(config_path,
                                              config.get("strategy_id", "COMPOUNDER"))
        self.watchlist = WatchlistManager(max_entries=config.get("max_watchlist", 50))
        self.ranking = RankingSystem()
        self.data_refresher = DataRefreshWorker(config)
        self.screener = FinvizScreener(
            resolve_config_directory(config.get("screeners_dir", "idos-config/screeners"))
        )
        self.journal_path = config.get("journal_path", "")

    def _save_watchlist(self):
        if not self.journal_path:
            return
        (Path(self.journal_path) / "portfolio").mkdir(parents=True, exist_ok=True)
        repo = JournalRepository(Path(self.journal_path))
        entries = [{"ticker": e.ticker, "score": e.score, "reason": e.reason,
                     "added_at": e.added_at, "alerts": e.alerts, "notified": e.notified}
                    for e in self.watchlist.entries]
        repo.save_watchlist(entries)
        print(f"[SCOUT] Watchlist saved to {self.journal_path}/portfolio/watchlist.yml ({len(entries)} entries)")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        tickers = context.get("tickers") or self._load_tickers()
        force_refresh = context.get("force_refresh", False)
        total_input = len(tickers)

        # ──────────────────────────────────────────────────────────
        # STEP 0: Data Fetch (asegurar datos financieros disponibles)
        # ──────────────────────────────────────────────────────────
        to_fetch = [
            ticker for ticker in tickers
            if not DataRefreshWorker._has_normalized_market_gates(self._get_cached_data(ticker))
        ]
        if to_fetch:
            print(f"\n[SCOUT] === STEP 0: Data Fetch ({len(to_fetch)} tickers) ===")
            refresh_ctx = {"tickers": to_fetch, "max_tickers": context.get("max_tickers", 0)}
            refresh_result = self.data_refresher.execute(refresh_ctx)
            if refresh_result.status == "failed":
                print(f"[SCOUT] Data fetch failed: {refresh_result.error}")
            else:
                fetched = refresh_result.output.get("tickers_processed", 0)
                print(f"[SCOUT] Data fetched for {fetched} tickers")

        # ──────────────────────────────────────────────────────────
        # STEP 1: FinvizScreener (0 LLM, reglas programaticas)
        # ──────────────────────────────────────────────────────────
        # The profile is the single financial preselection policy.
        screener_passed = list(tickers)
        screener_skipped = 0

        # ──────────────────────────────────────────────────────────
        # STEP 2: OperabilityFilter (solo activos operables)
        # ──────────────────────────────────────────────────────────
        operable = OperabilityFilter(
            self.config.get("operable_path", "idos-config/universe/operable.yml")
        )
        before = len(tickers)
        tickers = [t for t in tickers if operable.is_operable(t)]
        if before != len(tickers):
            print(f"[SCOUT] Operability: {before} -> {len(tickers)} tickers")
        if not tickers:
            print("[SCOUT] No tickers after operability filter")
            return {"tickers_screened": total_input, "passed_count": 0,
                    "screener_passed": len(screener_passed), "screener_filtered": screener_skipped,
                    "operable_passed": 0, "results": [], "watchlist_size": 0}
        operable_passed = len(tickers)

        # ──────────────────────────────────────────────────────────
        # STEP 3: ScoutEngine (score detallado)
        # ──────────────────────────────────────────────────────────
        print(f"\n[SCOUT] === STEP 3: ScoutEngine ({len(tickers)} tickers) ===")
        screened: list[dict[str, Any]] = []
        for i, ticker in enumerate(tickers, 1):
            financial_data = self._get_cached_data(ticker)
            scout_result = self._run_scout(ticker, financial_data)
            print(f"[SCOUT] [{i}/{len(tickers)}] {ticker}: score={scout_result.score} passed={scout_result.passed}")

            if scout_result.passed:
                self.watchlist.add(ticker=ticker, score=scout_result.score, reason=scout_result.reason)

            screened.append({
                "ticker": ticker,
                "scout_score": scout_result.score,
                "score": scout_result.score,
                "passed": scout_result.passed,
                "details": scout_result.details,
                "reason": scout_result.reason,
            })

        try:
            ranked = self.ranking.rank(screened)
        finally:
            self._save_watchlist()

        passed_entries = [e for e in screened if e["passed"]]
        passed_ranked = [r for r in ranked if any(e["ticker"] == r.ticker and e["passed"] for e in screened)]
        print(f"\n[SCOUT] === RESULTS ===")
        print(f"[SCOUT] Input: {total_input} | Screener: {len(screener_passed)} | Operable: {operable_passed} | Scored: {len(screened)} | Passed: {len(passed_entries)}")
        if passed_ranked:
            print("[SCOUT] Top scored:")
            for r in passed_ranked[:10]:
                print(f"  {r.ticker}: score={r.scout_score} rank={r.rank}")

        # ──────────────────────────────────────────────────────────
        # STEP 4: Data Refresh (solo para watchlisted)
        # ──────────────────────────────────────────────────────────
        watchlisted = [e["ticker"] for e in screened if e["passed"]]
        if watchlisted and (force_refresh or context.get("refresh_data", False)):
            print(f"\n[SCOUT] === STEP 4: Data Refresh ({len(watchlisted)} tickers) ===")
            refresh_ctx = {
                "tickers": watchlisted,
                "max_tickers": context.get("max_tickers", 0),
            }
            refresh_result = self.data_refresher.execute(refresh_ctx)
            if refresh_result.status == "failed":
                print(f"[SCOUT] Data refresh failed: {refresh_result.error}")
            else:
                data_map = refresh_result.output.get("data", {})
                print(f"[SCOUT] Data refreshed for {len(data_map)} tickers")

        passed_tickers = {e["ticker"] for e in screened if e["passed"]}
        return {
            "tickers_screened": total_input,
            "passed_count": len(passed_entries),
            "screener_passed": len(screener_passed),
            "screener_filtered": screener_skipped,
            "operable_passed": operable_passed,
            "results": [{"ticker": r.ticker, "scout_score": r.scout_score, "score": r.scout_score,
                         "conviction_score": r.conviction_score,
                         "combined_score": r.combined_score, "rank": r.rank, "reason": r.reason,
                         "passed": r.ticker in passed_tickers} for r in ranked],
            "watchlist_size": len(self.watchlist.entries),
        }

    def _get_cached_data(self, ticker: str) -> dict[str, Any]:
        try:
            cache = DataCache()
            data = cache.get(f"merged:{ticker}")
            if data:
                return DataRefreshWorker._cache_file_payload(data)
        except Exception:
            pass
        return {}

    def _run_scout(self, ticker: str, financial_data: dict[str, Any]) -> ScoutResult:
        return self.scout_engine.scan_market_data(ticker, financial_data)

    def _load_tickers(self) -> list[str]:
        if not self.universe_path:
            return self._load_from_operable()
        path = Path(self.universe_path)
        if not path.exists():
            return self._load_from_operable()
        if path.suffix in (".yml", ".yaml"):
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            entries = data.get("entries", []) if data else []
            return [e.get("ticker", "") for e in entries if e.get("ticker")]
        content = path.read_text(encoding="utf-8")
        tickers = re.findall(r"^\|\s*([A-Z]+)\s*\|", content, re.MULTILINE)
        seen = set()
        result = [t for t in tickers if not (t in seen or seen.add(t))]
        return result if result else self._load_from_operable()

    def _load_from_operable(self) -> list[str]:
        from idos.discovery.configured_scout import resolve_config_directory
        operable_path = resolve_config_directory(
            self.config.get("operable_path", "idos-config/universe/operable.yml")
        )
        try:
            from idos.discovery.operability import OperabilityFilter
            op = OperabilityFilter(operable_path)
            return sorted(op.tickers)
        except Exception:
            return []
