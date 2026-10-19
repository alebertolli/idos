import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

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
from idos.market.liquidity import (
    FxObservation,
    MarketDataNormalizationError,
    MarketDataSettings,
    MonedApiFxProvider,
    expected_us_market_sessions,
    normalize_average_dollar_turnover,
    normalize_market_cap_usd,
)


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
        self.config_root = config.get("config_path", "idos-config")
        self.market_data_settings = MarketDataSettings.load(self.config_root)
        self.fx_provider = MonedApiFxProvider()
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
            asset_type = self._asset_type_for_ticker(ticker)
            cached = self.cache.get(f"merged:{ticker}")
            cached_merged = cached.get("merged_data", cached) if isinstance(cached, dict) else {}
            if (
                cached
                and self._has_normalized_market_gates(cached)
                and isinstance(cached_merged, dict)
                and cached_merged.get("asset_type") == asset_type
            ):
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
                    yf_raw = source_data.get("yfinance", {})
                    if yf_raw.get("next_earnings_date"):
                        source_data.setdefault("stockanalysis.com", {}).setdefault(
                            "next_earnings_date", yf_raw["next_earnings_date"]
                        )
                    history = self._extract_price_history(yf_raw)
                    if history is None:
                        # StockAnalysis has no aligned OHLCV or quote-currency contract.
                        # Fetch Yahoo once for market history and its explicit currency.
                        try:
                            yf_result = self.retry.execute(
                                self.sources["yfinance"].execute,
                                {"ticker": ticker, "period": "1y"},
                            )
                            if yf_result and getattr(yf_result, "status", "") == "success":
                                yf_raw = yf_result.output or {}
                                history = self._extract_price_history(yf_raw)
                                self.cache.set(
                                    f"raw:yfinance:{ticker}", yf_raw,
                                    source="yfinance", ttl_seconds=43200,
                                )
                            else:
                                reason = (
                                    getattr(yf_result, "error", None)
                                    if yf_result else "Yahoo returned no response"
                                )
                                errors.append(f"{ticker}: Yahoo quote metadata unavailable ({reason})")
                        except Exception as e:
                            self.error_manager.report(
                                category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                                message=f"yfinance market data fallo: {e}",
                            )
                            errors.append(f"{ticker}: yfinance market data fail ({e})")

                    market_metrics = self._normalize_market_gate_metrics(ticker, yf_raw, history, asset_type=asset_type)
                    if "stockanalysis.com" in source_data and yf_raw:
                        # Add Yahoo as a source only for quote metadata, normalized gate
                        # fields and aligned history; do not average raw market-cap values.
                        source_data["yfinance"] = self._yahoo_market_source(yf_raw, history)
                        source_data["yfinance"].update(market_metrics)
                    elif "yfinance" in source_data:
                        source_data["yfinance"].update(market_metrics)

                    validated = self.validator.cross_validate(source_data)
                    merged = validated.get("merged_data", validated)
                    self._preserve_financial_observations(validated, source_data)
                    if history:
                        merged.setdefault("price_history", history["prices"])
                        merged.setdefault("volume_history", history["volumes"])
                        merged.setdefault("price_history_dates", history["dates"])
                        self._save_price_history(db, ticker, history)
                    for key, value in market_metrics.items():
                        merged[key] = value
                    validated["merged_data"] = merged
                    if history:
                        validated.setdefault("field_sources", {}).setdefault("price_history", ["yfinance"])
                    for key in ("market_cap_usd", "avg_dollar_volume_usd"):
                        if merged.get(key) is not None:
                            validated.setdefault("field_sources", {})[key] = ["yfinance"]
                    if "yfinance" in source_data:
                        validated["source_count"] = len(validated.get("sources_used", []))
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
        if (
            not prices or not dates or not volumes
            or len(prices) != len(dates) or len(volumes) != len(dates)
        ):
            return None
        return {
            "prices": prices,
            "dates": dates,
            "volumes": volumes,
            "price_basis": data.get("price_history_basis"),
        }

    @staticmethod
    def _has_normalized_market_gates(cached: dict[str, Any]) -> bool:
        merged = cached.get("merged_data", cached) if isinstance(cached, dict) else {}
        if not isinstance(merged, dict):
            return False
        size_metric = merged.get("size_metric_usd")
        dollar_volume = merged.get("avg_dollar_volume_usd")
        normalization = merged.get("market_data_normalization")
        asset_type = merged.get("asset_type")
        common_gates_complete = (
            asset_type in {"etf", "us_equity"}
            and isinstance(dollar_volume, (int, float)) and not isinstance(dollar_volume, bool)
            and math.isfinite(dollar_volume) and dollar_volume > 0
            and isinstance(merged.get("liquidity_provenance"), dict)
            and isinstance(normalization, dict) and normalization.get("status") == "complete"
        )
        if not common_gates_complete:
            return False
        if asset_type == "etf":
            return True  # ETFs require liquidity, not market cap or AUM.
        size_provenance = merged.get("size_metric_provenance")
        metric_provenance = merged.get("market_cap_provenance")
        try:
            provenance_date = date.fromisoformat(str(size_provenance.get("as_of", "")))
        except (AttributeError, TypeError, ValueError):
            provenance_date = None
        return bool(
            isinstance(size_metric, (int, float)) and not isinstance(size_metric, bool)
            and math.isfinite(size_metric) and size_metric > 0
            and merged.get("market_cap_usd") == size_metric
            and isinstance(size_provenance, dict)
            and bool(str(size_provenance.get("source", "")).strip())
            and provenance_date is not None
            and isinstance(metric_provenance, dict)
            and metric_provenance.get("source") == size_provenance.get("source")
            and metric_provenance.get("as_of") == size_provenance.get("as_of")
        )

    def _normalize_market_gate_metrics(
        self,
        ticker: str,
        yahoo_data: dict[str, Any],
        history: dict[str, list] | None,
        *,
        asset_type: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "asset_type": asset_type,
            "market_data_normalization": {"status": "blocked", "errors": []}
        }
        errors = result["market_data_normalization"]["errors"]
        provider_errors = yahoo_data.get("provider_errors", []) if isinstance(yahoo_data, dict) else []
        if isinstance(provider_errors, list):
            errors.extend(f"Yahoo {error}" for error in provider_errors if error)
        if asset_type not in {"etf", "us_equity"}:
            errors.append("Explicit supported asset type missing from operable universe")
        if not yahoo_data:
            errors.append("Yahoo quote metadata unavailable")
            return result
        currency = yahoo_data.get("quote_currency")
        if not isinstance(currency, str) or not currency.strip():
            errors.append("Yahoo quote currency missing")
        if not history:
            errors.append("Aligned daily price and volume history unavailable")
        elif history.get("price_basis") != "close_unadjusted":
            errors.append("Price history does not declare unadjusted closing prices")

        fx_reference = yahoo_data.get("fx_reference") or self._fx_reference_for_ticker(ticker)
        fx_observations: list[FxObservation] = []
        expected_dates: list[date] = []
        last_market_date = None
        if history and history.get("dates"):
            try:
                last_market_date = date.fromisoformat(str(history["dates"][-1])[:10])
                exchange = yahoo_data.get("exchange")
                expected_dates = expected_us_market_sessions(
                    last_market_date - timedelta(days=60), last_market_date, exchange
                )[-self.market_data_settings.liquidity.window_sessions :]
                if currency and currency.upper() == "ARS":
                    if not fx_reference:
                        raise MarketDataNormalizationError("ARS asset requires an explicit MEP or CCL reference")
                    fx_from = (expected_dates[0] - timedelta(days=self.market_data_settings.liquidity.max_fx_staleness_days))
                    fx_observations = self.fx_provider.history(
                        fx_reference, fx_from, expected_dates[-1]
                    )
            except (ValueError, IndexError, MarketDataNormalizationError) as exc:
                errors.append(str(exc))

        rows = []
        if history and history.get("price_basis") == "close_unadjusted":
            rows = [
                {
                    "date": market_date,
                    "close": close,
                    "volume": volume,
                    "price_basis": "close_unadjusted",
                    "source": "yfinance",
                }
                for market_date, close, volume in zip(
                    history.get("dates", []), history.get("prices", []), history.get("volumes", [])
                )
            ]
            if currency and expected_dates:
                try:
                    result.update(normalize_average_dollar_turnover(
                        rows,
                        expected_market_dates=expected_dates,
                        quote_currency=currency,
                        source="yfinance",
                        fx_reference=fx_reference,
                        fx_observations=fx_observations,
                        policy=self.market_data_settings.liquidity,
                    ))
                except MarketDataNormalizationError as exc:
                    errors.append(str(exc))
        size_metric = None
        size_provenance = None
        if asset_type == "us_equity":
            cap_currency = yahoo_data.get("market_cap_currency")
            market_cap = yahoo_data.get("market_cap")
            if market_cap is not None and cap_currency and last_market_date:
                try:
                    result.update(normalize_market_cap_usd(
                        market_cap, currency=cap_currency, as_of=last_market_date,
                        source="yfinance", fx_reference=fx_reference,
                        fx_observations=fx_observations,
                        max_fx_staleness_days=self.market_data_settings.liquidity.max_fx_staleness_days,
                    ))
                    size_metric = result["market_cap_usd"]
                    size_provenance = result["market_cap_provenance"]
                except MarketDataNormalizationError as exc:
                    errors.append(str(exc))
            else:
                errors.append("Market cap value, explicit currency or market date missing")
        if size_metric is not None:
            result["size_metric_usd"] = size_metric
            result["size_metric_provenance"] = size_provenance

        result["market_data_normalization"] = {
            "status": "complete" if not errors and (asset_type == "etf" or size_metric is not None) and result.get("avg_dollar_volume_usd") is not None else "blocked",
            "size_metric": "market_cap_usd" if asset_type == "us_equity" else None,
            "errors": errors,
            "liquidity_basis": "UNDERLYING_USD_PROXY",
            "exchange_calendar": yahoo_data.get("exchange"),
        }
        if result.get("liquidity_provenance"):
            result["liquidity_provenance"]["basis"] = "UNDERLYING_USD_PROXY"
        return result

    def _asset_type_for_ticker(self, ticker: str) -> str | None:
        path = Path(self.config.get("operable_path", Path(self.config_root) / "universe" / "operable.yml"))
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for entry in document.get("operable_tickers", []):
                if str(entry.get("ticker", "")).upper() == ticker.upper():
                    return str(entry.get("type", "")).lower() or None
        except (OSError, TypeError, yaml.YAMLError):
            return None
        return None

    def _fx_reference_for_ticker(self, ticker: str) -> str | None:
        universe_path = Path(self.config.get(
            "operable_path", Path(self.config_root) / "universe" / "operable.yml"
        ))
        try:
            import yaml
            document = yaml.safe_load(universe_path.read_text(encoding="utf-8")) or {}
            for entry in document.get("operable_tickers", []):
                if str(entry.get("ticker", "")).upper() == ticker.upper():
                    reference = entry.get("fx_reference")
                    return str(reference).upper() if reference else None
        except (OSError, TypeError, yaml.YAMLError):
            return None
        return None

    @staticmethod
    def _preserve_financial_observations(validated: dict, sources: dict) -> None:
        """Do not average fundamentals from potentially different reporting periods."""
        merged = validated["merged_data"]
        observations = {}
        for field in ("operating_margin_pct", "revenue_growth_pct", "fcf"):
            values = {source: data[field] for source, data in sources.items()
                      if isinstance(data.get(field), (int, float))
                      and not isinstance(data[field], bool) and math.isfinite(data[field])}
            if not values:
                continue
            selected = "yfinance" if "yfinance" in values else next(iter(values))
            merged[field] = values[selected]
            validated.setdefault("field_sources", {})[field] = [selected]
            observations[field] = {
                "selected_source": selected, "values": values,
                "observed_at": sources[selected].get("financial_data_observed_at"),
                "provider_period_end_timestamp": sources[selected].get("financial_period_end_timestamp"),
                "unit": "provider_financial_currency" if field == "fcf" else "percentage_points",
                "currency": sources[selected].get("financial_currency") if field == "fcf" else None,
                "period_status": "PROVIDER_REPORTED_NOT_RECONCILED",
            }
        merged["financial_observations"] = observations

    @staticmethod
    def _yahoo_market_source(yahoo_data: dict[str, Any], history: dict[str, list] | None) -> dict[str, Any]:
        keys = (
            "ticker", "source", "quote_currency", "market_cap_currency", "market_cap",
            "exchange",
            "price_history", "volume_history", "price_history_dates",
            "price_history_basis",
            "fcf", "operating_margin_pct", "revenue_growth_pct",
            "financial_currency", "financial_data_observed_at", "financial_period_end_timestamp",
        )
        result = {key: yahoo_data[key] for key in keys if key in yahoo_data}
        if history:
            result.update({
                "price_history": history["prices"],
                "volume_history": history["volumes"],
                "price_history_dates": history["dates"],
                "price_history_basis": history["price_basis"],
            })
        return result

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
