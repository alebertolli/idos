import re
from pathlib import Path
from typing import Any, Optional

from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.resilience.error_manager import (
    ErrorManager,
    CATEGORY_DATOS,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from idos.resilience.retry import RetryMechanism, RetryPolicy
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
        self.db = SQLiteStore(Path.cwd() / "idos.db")
        self.error_manager = ErrorManager()
        self.retry = RetryMechanism(RetryPolicy(max_retries=3, base_delay=1.0, max_delay=8.0))
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

            db = self.db
            try:
                source_data = {}
                print(f"[REFRESH] {ticker}: fetching stockanalysis...", end=" ")
                try:
                    sa_data = self.retry.execute(
                        self.sources["stockanalysis"].execute, {"ticker": ticker}
                    )
                except Exception as e:
                    sa_data = None
                    print(f"fail ({e})")
                    self.error_manager.report(
                        category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                        message=f"stockanalysis.com fallo: {e}",
                    )
                    errors.append(f"{ticker}: stockanalysis fail ({e})")

                if sa_data and getattr(sa_data, "status", "") == "success":
                    source_data["stockanalysis.com"] = sa_data.output
                    self.cache.set(
                        f"raw:stockanalysis:{ticker}",
                        sa_data.output,
                        source="stockanalysis.com",
                        ttl_seconds=43200,
                    )
                    print("ok")
                else:
                    print(f"[REFRESH] {ticker}: fetching yfinance...", end=" ")
                    try:
                        yf_data = self.retry.execute(
                            self.sources["yfinance"].execute, {"ticker": ticker}
                        )
                    except Exception as e:
                        yf_data = None
                        print(f"fail ({e})")
                        self.error_manager.report(
                            category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                            message=f"yfinance fallo: {e}",
                        )
                        errors.append(f"{ticker}: yfinance fail ({e})")

                    if yf_data and getattr(yf_data, "status", "") == "success":
                        source_data["yfinance"] = yf_data.output
                        self.cache.set(
                            f"raw:yfinance:{ticker}",
                            yf_data.output,
                            source="yfinance",
                            ttl_seconds=43200,
                        )
                        print("ok")
                    else:
                        yf_msg = (getattr(yf_data, "error", None) or "sin datos") if yf_data else "sin respuesta"
                        print(f"fail ({yf_msg})")
                        self.error_manager.report(
                            category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                            message=f"yfinance sin datos: {yf_msg}",
                        )
                        errors.append(f"{ticker}: yfinance no data ({yf_msg})")

                if len(source_data) > 0:
                    if "stockanalysis.com" not in source_data and "yfinance" in source_data:
                        self.error_manager.report(
                            category=CATEGORY_DATOS, severity=SEVERITY_LOW, ticker=ticker,
                            message="degradacion de fuente: fallback a yfinance",
                            detail="SDD-16 Capa 6: la degradacion siempre debe registrarse",
                        )
                    validated = self.validator.cross_validate(source_data)
                    merged = validated.get("merged_data", validated)
                    yf_raw = source_data.get("yfinance", {})
                    if yf_raw.get("next_earnings_date"):
                        merged.setdefault("next_earnings_date", yf_raw["next_earnings_date"])
                    history = self._extract_price_history(yf_raw)
                    if history is None:
                        # StockAnalysis does not currently provide aligned daily history.
                        # Fetch it only when the Yahoo worker was not already the source.
                        try:
                            import yfinance as yf
                            hist = yf.Ticker(ticker).history(period="1y")
                            if not hist.empty:
                                history = {
                                    "prices": hist["Close"].tolist(),
                                    "volumes": hist["Volume"].tolist(),
                                    "dates": [str(d.date()) for d in hist.index],
                                }
                        except Exception as e:
                            self.error_manager.report(
                                category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                                message=f"yfinance history fallo: {e}",
                            )
                    if history:
                        merged.setdefault("price_history", history["prices"])
                        merged.setdefault("volume_history", history["volumes"])
                        merged.setdefault("price_history_dates", history["dates"])
                        self._save_price_history(db, ticker, history)
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
                    cache_payload = self._cache_file_payload(validated)
                    (cache_dir / f"{ticker}.json").write_text(
                        json.dumps(cache_payload, default=str, indent=2), encoding="utf-8"
                    )
                    self._save_company_info(ticker, merged)
                else:
                    msg = "no data from any source"
                    self.error_manager.report(
                        category=CATEGORY_DATOS, severity=SEVERITY_HIGH, ticker=ticker,
                        message=msg,
                    )
                    errors.append(f"{ticker}: {msg}")
            except Exception as e:
                self.error_manager.report(
                    category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                    message=f"error de refresco: {e}",
                )
                errors.append(f"{ticker}: {str(e)}")

        return {
            "tickers_processed": len(results),
            "tickers": list(results.keys()),
            "errors": errors,
            "data": results,
        }

    @staticmethod
    def _extract_price_history(data: dict[str, Any]) -> dict[str, list] | None:
        prices = data.get("price_history", [])
        dates = data.get("price_history_dates", [])
        volumes = data.get("volume_history", [])
        if not prices or not dates or len(prices) != len(dates):
            return None
        return {"prices": prices, "dates": dates, "volumes": volumes}

    @staticmethod
    def _cache_file_payload(validated: dict[str, Any]) -> dict[str, Any]:
        """Keep the flat metrics contract and attach auditable source provenance."""
        merged = validated.get("merged_data", validated)
        payload = dict(merged)
        provenance_keys = ("source_count", "sources_used", "field_sources", "conflicts")
        provenance = {key: validated[key] for key in provenance_keys if key in validated}
        if provenance:
            payload["data_provenance"] = provenance
        return payload

    @staticmethod
    def _save_price_history(db: SQLiteStore, ticker: str, history: dict[str, list]) -> None:
        last_date = db.get_last_price_date(ticker)
        rows = [
            {"date": date, "close": price, "volume": history["volumes"][i] if i < len(history["volumes"]) else 0}
            for i, (date, price) in enumerate(zip(history["dates"], history["prices"]))
            if not last_date or date > last_date
        ]
        if rows:
            db.save_price_history(ticker, rows)

    def _save_company_info(self, ticker: str, info: dict[str, Any] | None = None):
        try:
            from pathlib import Path
            import yaml
            base = Path.cwd() / "idos-knowledge" / "companies" / ticker
            company_file = base / "company.yml"
            if company_file.exists():
                existing = yaml.safe_load(company_file.read_text(encoding="utf-8")) or {}
                if existing.get("sector"):
                    return
            info = info or {}
            resolved = (info.get("symbol") or ticker).upper().strip()
            if resolved != ticker:
                print(f"[WARN] {ticker}: yfinance resolved to {resolved}, skipping yfinance company info")
                return
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
        except Exception as e:
            self.error_manager.report(
                category=CATEGORY_DATOS, severity=SEVERITY_LOW, ticker=ticker,
                message=f"company info guardado fallo: {e}",
            )

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
