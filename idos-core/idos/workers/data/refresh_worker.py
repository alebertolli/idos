import re
from pathlib import Path
from typing import Any, Optional

from idos.workers.base import BaseWorker
from idos.workers.data.stockanalysis import StockAnalysisWorker
from idos.workers.data.yahoo import YahooFinanceWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.validator import DataValidator


class DataRefreshWorker(BaseWorker):
    name = "data_refresh"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.cache = DataCache()
        self.validator = DataValidator()
        self.universe_path = config.get("universe_path", "")
        self.sources = {
            "stockanalysis": StockAnalysisWorker(config),
            "yfinance": YahooFinanceWorker(config),
        }

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        tickers = context.get("tickers") or self._load_tickers_from_universe()
        max_tickers = context.get("max_tickers", 0)

        if max_tickers and len(tickers) > max_tickers:
            tickers = tickers[:max_tickers]

        results: dict[str, Any] = {}
        errors: list[str] = []

        for ticker in tickers:
            ticker = ticker.upper().strip()
            cached = self.cache.get(f"merged:{ticker}")
            if cached:
                results[ticker] = cached
                continue

            try:
                source_data = {}
                print(f"[REFRESH] {ticker}: fetching stockanalysis...", end=" ")
                sa_data = self.sources["stockanalysis"].execute({"ticker": ticker})
                if sa_data.status == "success":
                    source_data["stockanalysis.com"] = sa_data.output
                    self.cache.set(
                        f"raw:stockanalysis:{ticker}",
                        sa_data.output,
                        source="stockanalysis.com",
                        ttl_seconds=43200,
                    )
                    print("ok")
                else:
                    print(f"fail ({sa_data.error})")

                if "stockanalysis.com" not in source_data:
                    print(f"[REFRESH] {ticker}: fetching yfinance...", end=" ")
                    yf_data = self.sources["yfinance"].execute({"ticker": ticker})
                    if yf_data.status == "success":
                        source_data["yfinance"] = yf_data.output
                        self.cache.set(
                            f"raw:yfinance:{ticker}",
                            yf_data.output,
                            source="yfinance",
                            ttl_seconds=43200,
                        )
                        print("ok")
                    else:
                        print(f"fail ({yf_data.error})")

                if len(source_data) > 0:
                    validated = self.validator.cross_validate(source_data)
                    results[ticker] = validated
                    self.cache.set(
                        f"merged:{ticker}",
                        validated,
                        source="merged",
                        ttl_seconds=3600,
                    )
                    import json
                    cache_dir = Path("cache")
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    (cache_dir / f"{ticker}.json").write_text(
                        json.dumps(validated, default=str, indent=2), encoding="utf-8"
                    )
                else:
                    errors.append(f"{ticker}: no data from any source")
            except Exception as e:
                errors.append(f"{ticker}: {str(e)}")

        return {
            "tickers_processed": len(results),
            "tickers": list(results.keys()),
            "errors": errors,
            "data": results,
        }

    def _load_tickers_from_universe(self) -> list[str]:
        if not self.universe_path:
            return []
        path = Path(self.universe_path)
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        tickers = re.findall(r"^\|\s*([A-Z]+)\s*\|", content, re.MULTILINE)
        seen = set()
        unique = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique
