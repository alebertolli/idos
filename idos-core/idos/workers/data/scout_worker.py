import re
from pathlib import Path
from typing import Any

from idos.discovery.scout import ScoutEngine, ScoutResult
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.workers.base import BaseWorker
from idos.workers.data.refresh_worker import DataRefreshWorker


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

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        tickers = context.get("tickers") or self._load_tickers()
        force_refresh = context.get("force_refresh", False)

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
        for i, ticker in enumerate(tickers, 1):
            financial_data = data_map.get(ticker, {}).get("merged_data", {})
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

        ranked = self.ranking.rank(screened)

        passed_entries = [e for e in screened if e["passed"]]
        passed_ranked = [r for r in ranked if any(e["ticker"] == r.ticker and e["passed"] for e in screened)]
        print(f"\n[SCOUT] Done: {len(screened)} screened, {len(passed_entries)} passed")
        if passed_ranked:
            print("[SCOUT] Passed:")
            for r in passed_ranked:
                print(f"  {r.ticker}: score={r.scout_score} rank={r.rank}")

        return {
            "tickers_screened": len(screened),
            "passed_count": sum(1 for s in screened if s["passed"]),
            "results": [{"ticker": r.ticker, "scout_score": r.scout_score, "conviction_score": r.conviction_score,
                         "combined_score": r.combined_score, "rank": r.rank, "reason": r.reason} for r in ranked],
            "watchlist_size": len(self.watchlist.entries),
        }

    def _run_scout(self, ticker: str, financial_data: dict[str, Any]) -> ScoutResult:
        metrics = {
            "market_cap": financial_data.get("market_cap", 0),
            "avg_volume": financial_data.get("volume_avg", 0) or financial_data.get("avg_volume", 0),
            "pe_ratio": financial_data.get("pe_ratio_ttm") or financial_data.get("pe_ratio", 0),
            "ev_ebitda": financial_data.get("ev_ebitda", 0),
            "roic": financial_data.get("roic_pct", 0),
            "operating_margin": financial_data.get("operating_margin_pct", 0),
            "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
            "revenue_growth": financial_data.get("revenue_growth_pct", 0),
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
