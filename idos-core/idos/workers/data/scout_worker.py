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
from idos.data.journal import JournalRepository


class ScoutWorker(BaseWorker):
    name = "scout_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.universe_path = config.get("universe_path", "")
        self.scout_engine = ScoutEngine(min_score=config.get("min_score", 50))
        self.watchlist = WatchlistManager(max_entries=config.get("max_watchlist", 50))
        self.ranking = RankingSystem()
        self.data_refresher = DataRefreshWorker(config)
        self.screener = FinvizScreener(
            config.get("screeners_dir", "idos-config/screeners")
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

        operable = OperabilityFilter(
            self.config.get("operable_path", "idos-config/universe/operable.yml")
        )
        before = len(tickers)
        tickers = [t for t in tickers if operable.is_operable(t)]
        if before != len(tickers):
            print(f"[SCOUT] Operability filter: {before} -> {len(tickers)} tickers")
        if not tickers:
            print("[SCOUT] No operable tickers to screen")
            return {"tickers_screened": 0, "passed_count": 0, "results": [], "watchlist_size": 0}

        print(f"\n[SCOUT] Screening {len(tickers)} tickers (refresh={force_refresh})")

        if force_refresh or context.get("refresh_data", False):
            refresh_ctx = {
                "tickers": tickers,
                "max_tickers": context.get("max_tickers", 0),
            }
            refresh_result = self.data_refresher.execute(refresh_ctx)
            if refresh_result.status == "failed":
                print(f"[SCOUT] Data refresh failed: {refresh_result.error}")
                data_map = {}
            else:
                data_map = refresh_result.output.get("data", {})
            print(f"[SCOUT] Data refreshed for {len(data_map)} tickers")
        else:
            data_map = {}
            print("[SCOUT] Using cached data")

        screened: list[dict[str, Any]] = []
        screener_passed = 0
        screener_failed = 0
        for i, ticker in enumerate(tickers, 1):
            financial_data = data_map.get(ticker, {}).get("merged_data", {})
            screener_results = self.screener.run_all(financial_data)
            if not any(screener_results.values()):
                screener_failed += 1
                continue
            screener_passed += 1
            scout_result = self._run_scout(ticker, financial_data)
            print(f"[SCOUT] [{i}/{len(tickers)}] {ticker}: score={scout_result.score} passed={scout_result.passed} details={scout_result.details}")

            self.watchlist.add(
                ticker=ticker,
                score=scout_result.score,
                reason=scout_result.reason,
            )

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
        print(f"\n[SCOUT] Done: {len(screened)} screened, {len(passed_entries)} passed")
        print(f"[SCOUT] Screener: {screener_passed} passed, {screener_failed} failed")
        if passed_ranked:
            print("[SCOUT] Passed:")
            for r in passed_ranked:
                print(f"  {r.ticker}: score={r.scout_score} rank={r.rank}")

        passed_tickers = {e["ticker"] for e in screened if e["passed"]}
        return {
            "tickers_screened": len(screened),
            "passed_count": len(passed_entries),
            "screener_passed": screener_passed,
            "screener_failed": screener_failed,
            "results": [{"ticker": r.ticker, "scout_score": r.scout_score, "score": r.scout_score,
                         "conviction_score": r.conviction_score,
                         "combined_score": r.combined_score, "rank": r.rank, "reason": r.reason,
                         "passed": r.ticker in passed_tickers} for r in ranked],
            "watchlist_size": len(self.watchlist.entries),
        }

    def _run_scout(self, ticker: str, financial_data: dict[str, Any]) -> ScoutResult:
        def _num(v: Any, default: float = 0.0) -> float:
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v.replace(",", "").replace("$", "").replace("%", ""))
                except (ValueError, TypeError):
                    pass
            return default

        metrics = {
            "market_cap": _num(financial_data.get("market_cap")),
            "avg_volume": _num(financial_data.get("volume_avg")) or _num(financial_data.get("avg_volume")),
            "pe_ratio": _num(financial_data.get("pe_ratio_ttm")) or _num(financial_data.get("pe_ratio")),
            "ev_ebitda": _num(financial_data.get("ev_ebitda")),
            "roic": _num(financial_data.get("roic_pct")),
            "operating_margin": _num(financial_data.get("operating_margin_pct")),
            "debt_to_equity": _num(financial_data.get("debt_equity_ratio")),
            "revenue_growth": _num(financial_data.get("revenue_growth_pct")),
        }
        data = {"metrics": metrics}
        return self.scout_engine.scan(ticker=ticker, data=data)

    def _load_tickers(self) -> list[str]:
        if not self.universe_path:
            return []
        path = Path(self.universe_path)
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        tickers = re.findall(r"^\|\s*([A-Z]+)\s*\|", content, re.MULTILINE)
        seen = set()
        return [t for t in tickers if not (t in seen or seen.add(t))]
