import re
from pathlib import Path
from typing import Any, Optional

from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
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

            db = SQLiteStore(Path.cwd() / "idos.db")
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
                    merged = validated.get("merged_data", validated)
                    try:
                        import yfinance as yf
                        yfinfo = yf.Ticker(ticker).info or {}
                        et = yfinfo.get("earningsTimestamp")
                        if et:
                            merged["next_earnings_date"] = et
                    except Exception:
                        pass
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
                        json.dumps(merged if "merged_data" in validated else validated, default=str, indent=2), encoding="utf-8"
                    )
                    self._save_company_info(ticker)
                    last_date = db.get_last_price_date(ticker)
                    yf_raw = source_data.get("yfinance", {})
                    prices = yf_raw.get("price_history", [])
                    dates = yf_raw.get("price_history_dates", [])
                    volumes = yf_raw.get("volume_history", [])
                    if prices and dates and len(prices) == len(dates):
                        new_rows = []
                        for i in range(len(prices)):
                            d = dates[i]
                            if last_date and d <= last_date:
                                continue
                            new_rows.append({
                                "date": d,
                                "close": prices[i],
                                "volume": volumes[i] if i < len(volumes) else 0,
                            })
                        if new_rows:
                            db.save_price_history(ticker, new_rows)
                            print(f"[REFRESH] {ticker}: {len(new_rows)} nuevos registros en price_history")
                    else:
                        print(f"[REFRESH] {ticker}: sin price_history de yfinance")
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

    @staticmethod
    def _save_company_info(ticker: str):
        try:
            from pathlib import Path
            import yaml
            base = Path.cwd() / "idos-knowledge" / "companies" / ticker
            company_file = base / "company.yml"
            if company_file.exists():
                existing = yaml.safe_load(company_file.read_text(encoding="utf-8")) or {}
                if existing.get("sector"):
                    return
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            sector = info.get("sector", "")
            if not sector:
                return
            base.mkdir(parents=True, exist_ok=True)
            existing = {}
            if company_file.exists():
                existing = yaml.safe_load(company_file.read_text(encoding="utf-8")) or {}
            existing.setdefault("ticker", ticker)
            existing.setdefault("name", info.get("longName", "") or info.get("shortName", "") or ticker)
            existing.setdefault("sector", sector)
            existing.setdefault("industry", info.get("industry", ""))
            existing.setdefault("business_model", (info.get("longBusinessSummary") or "")[:500])
            company_file.write_text(yaml.dump(existing, default_flow_style=False, allow_unicode=True), encoding="utf-8")
            print(f"[INFO] {ticker}: company info saved to knowledge repo")
        except Exception:
            pass

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
