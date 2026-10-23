import math
import re
from datetime import date, datetime
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
from idos.workers.data.sec_edgar import SECEdgarWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.validator import DataValidator
from idos.market.liquidity import (
    MarketDataSettings,
    is_equity_asset_type,
    normalize_average_dollar_turnover,
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
        self.data_sources_config = self._load_data_sources_config()
        configured_sources = self.data_sources_config.get("sources", {})
        sec_config = configured_sources.get("sec_edgar", {}) if isinstance(configured_sources, dict) else {}
        self.sec_data_config = sec_config if isinstance(sec_config, dict) else {}
        self.sources = {
            "stockanalysis": StockAnalysisWorker(config),
            "yfinance": YahooFinanceWorker(config),
        }
        if self.sec_data_config.get("enabled") is True:
            self.sources["sec_edgar"] = SECEdgarWorker(self.sec_data_config)

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
                sa_data = None
                if asset_type != "etf":
                    print(f"[REFRESH] {ticker}: fetching stockanalysis...", end=" ")
                    try:
                        sa_data = self.retry.execute(
                            self.sources["stockanalysis"].execute, {"ticker": ticker}
                        )
                    except Exception as e:
                        print(f"fail ({e})")
                        self.error_manager.report(
                            category=CATEGORY_DATOS, severity=SEVERITY_MEDIUM, ticker=ticker,
                            message=f"stockanalysis.com fallo: {e}",
                        )
                        errors.append(f"{ticker}: stockanalysis fail ({e})")
                else:
                    print(f"[REFRESH] {ticker}: StockAnalysis no aplica a ETF. ", end="")

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

                sec_data = self._fetch_sec_fundamentals(ticker, asset_type)
                if sec_data:
                    source_data["sec_edgar"] = sec_data

                if len(source_data) > 0:
                    if (
                        asset_type != "etf"
                        and "stockanalysis.com" not in source_data
                        and "yfinance" in source_data
                    ):
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

    def _load_data_sources_config(self) -> dict[str, Any]:
        path = Path(self.config.get("data_sources_path", Path(self.config_root) / "data_sources.yml"))
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, TypeError, yaml.YAMLError):
            return {}
        return document if isinstance(document, dict) else {}

    def _fetch_sec_fundamentals(self, ticker: str, asset_type: str | None) -> dict[str, Any] | None:
        """Fetch regulator-filed fundamentals only for supported public equities."""
        worker = self.sources.get("sec_edgar")
        if not is_equity_asset_type(asset_type) or worker is None or not getattr(worker, "user_agent", None):
            return None

        cache_key = f"raw:sec_edgar:{ticker}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        try:
            result = self.retry.execute(
                worker.execute,
                {"ticker": ticker, "include_filings": False},
            )
        except Exception as exc:
            self.error_manager.report(
                category=CATEGORY_DATOS, severity=SEVERITY_LOW, ticker=ticker,
                message=f"SEC fundamentals unavailable: {type(exc).__name__}",
            )
            return None
        if not result or getattr(result, "status", "") != "success":
            reason = getattr(result, "error", None) or "SEC CompanyFacts unavailable"
            self.error_manager.report(
                category=CATEGORY_DATOS, severity=SEVERITY_LOW, ticker=ticker,
                message=f"SEC fundamentals unavailable: {reason}",
            )
            return None

        data = result.output if isinstance(result.output, dict) else {}
        if not any(data.get(field) is not None for field in ("revenue_growth_pct", "operating_margin_pct", "fcf")):
            return None
        ttl = self.sec_data_config.get("ttl_seconds", 86400)
        self.cache.set(cache_key, data, source="sec_edgar", ttl_seconds=int(ttl))
        return data

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
        is_equity = is_equity_asset_type(asset_type)
        common_gates_complete = (
            (asset_type == "etf" or is_equity)
            and isinstance(dollar_volume, (int, float)) and not isinstance(dollar_volume, bool)
            and math.isfinite(dollar_volume) and dollar_volume > 0
            and isinstance(merged.get("liquidity_provenance"), dict)
            and merged["liquidity_provenance"].get("currency") == "USD"
            and bool(str(merged["liquidity_provenance"].get("source", "")).strip())
            and bool(str(merged["liquidity_provenance"].get("as_of", "")).strip())
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
            and metric_provenance.get("currency") == "USD"
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
            "quote_currency": (
                yahoo_data.get("quote_currency").strip().upper()
                if isinstance(yahoo_data.get("quote_currency"), str)
                and re.fullmatch(r"[A-Za-z]{3}", yahoo_data["quote_currency"].strip())
                else None
            ),
            "market_data_normalization": {"status": "blocked", "errors": []}
        }
        errors = result["market_data_normalization"]["errors"]
        provider_errors = yahoo_data.get("provider_errors", []) if isinstance(yahoo_data, dict) else []
        if isinstance(provider_errors, list):
            errors.extend(f"Yahoo {error}" for error in provider_errors if error)
        if asset_type != "etf" and not is_equity_asset_type(asset_type):
            errors.append("Unsupported or missing operable asset class")
        if not yahoo_data:
            errors.append("Yahoo quote metadata unavailable")
            return result
        currency = yahoo_data.get("quote_currency")
        last_market_date = None
        if history and history.get("dates"):
            try:
                last_market_date = date.fromisoformat(str(history["dates"][-1])[:10])
            except ValueError:
                errors.append("Market history has an invalid observation date")
        as_of = last_market_date or date.today()

        direct_volume = yahoo_data.get("avg_dollar_volume_usd")
        direct_volume_provenance = yahoo_data.get("liquidity_provenance")
        if self._positive_finite(direct_volume) is not None:
            result["avg_dollar_volume_usd"] = float(direct_volume)
            result["liquidity_provenance"] = self._usd_metric_provenance(
                direct_volume_provenance, source="yahoo", as_of=as_of,
                basis="USD_PROVIDER_METRIC",
            )
        elif currency and currency.strip().upper() == "USD" and history and history.get("price_basis") == "close_unadjusted":
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
            observed_dates = []
            for row in rows:
                try:
                    observed_dates.append(date.fromisoformat(str(row["date"])[:10]))
                except (TypeError, ValueError):
                    continue
            if observed_dates:
                result.update(normalize_average_dollar_turnover(
                    rows,
                    expected_market_dates=observed_dates,
                    quote_currency="USD",
                    source="yfinance",
                    policy=self.market_data_settings.liquidity,
                ))
                result["liquidity_provenance"].update({
                    "basis": "UNDERLYING_USD_PROXY", "source": "yfinance",
                    "currency": "USD", "as_of": observed_dates[-1].isoformat(),
                })
        elif not history and direct_volume is None:
            errors.append("USD-denominated average dollar volume metric unavailable")
        elif direct_volume is None:
            errors.append("USD-denominated volume metric unavailable; local-currency FX conversion is not used")

        size_metric = None
        size_provenance = None
        if is_equity_asset_type(asset_type):
            direct_market_cap = yahoo_data.get("market_cap_usd")
            if self._positive_finite(direct_market_cap) is not None:
                size_metric = float(direct_market_cap)
                size_provenance = self._usd_metric_provenance(
                    yahoo_data.get("market_cap_provenance"), source="yahoo", as_of=as_of,
                    basis="USD_PROVIDER_METRIC",
                )
                result["market_cap_usd"] = size_metric
                result["market_cap_provenance"] = size_provenance
            elif str(yahoo_data.get("market_cap_currency", "")).strip().upper() == "USD" and self._positive_finite(yahoo_data.get("market_cap")) is not None:
                size_metric = float(yahoo_data["market_cap"])
                size_provenance = self._usd_metric_provenance(
                    yahoo_data.get("market_cap_provenance"), source="yfinance", as_of=as_of,
                    basis="USD_PROVIDER_METRIC",
                )
                result["market_cap_usd"] = size_metric
                result["market_cap_provenance"] = size_provenance
            else:
                errors.append("USD-denominated market capitalization metric unavailable")
        if size_metric is not None:
            result["size_metric_usd"] = size_metric
            result["size_metric_provenance"] = size_provenance

        result["market_data_normalization"] = {
            "status": "complete" if (asset_type == "etf" or is_equity_asset_type(asset_type) and size_metric is not None) and result.get("avg_dollar_volume_usd") is not None else "blocked",
            "size_metric": "market_cap_usd" if is_equity_asset_type(asset_type) else None,
            "errors": errors,
            "liquidity_basis": (result.get("liquidity_provenance") or {}).get("basis"),
            "geography_filter": None,
            "fx_conversion_used": False,
        }
        return result

    @staticmethod
    def _positive_finite(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed > 0 else None

    @staticmethod
    def _usd_metric_provenance(raw: Any, *, source: str, as_of: date, basis: str) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        observed_source = str(raw.get("source") or source).strip()
        observed_date = str(raw.get("as_of") or as_of.isoformat()).strip()
        try:
            date.fromisoformat(observed_date)
        except ValueError:
            observed_date = as_of.isoformat()
        return {"source": observed_source, "as_of": observed_date, "currency": "USD", "basis": basis}

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

    @staticmethod
    def _preserve_financial_observations(validated: dict, sources: dict) -> None:
        """Keep source-specific fundamentals and use only comparable values for gates."""
        merged = validated["merged_data"]
        observations = {}
        conflicts = {
            item.get("field") for item in validated.get("conflicts", [])
            if isinstance(item, dict)
        }
        non_comparable = {
            item.get("field"): item
            for item in validated.get("non_comparable", [])
            if isinstance(item, dict) and isinstance(item.get("field"), str)
        }
        for field in ("operating_margin_pct", "revenue_growth_pct", "fcf"):
            values = {source: data[field] for source, data in sources.items()
                      if isinstance(data.get(field), (int, float))
                      and not isinstance(data[field], bool) and math.isfinite(data[field])}
            if not values:
                continue
            exclusion = non_comparable.get(field, {})
            excluded_sources = set(exclusion.get("excluded_sources", []))
            comparable_values = {
                source: value for source, value in values.items()
                if source not in excluded_sources
            }
            if not comparable_values:
                comparable_values = {
                    source: value for source, value in values.items()
                    if source == exclusion.get("selected_source")
                }
            candidate_values = comparable_values or values
            selected = DataRefreshWorker._preferred_financial_source(candidate_values)
            excluded_sources.discard(selected)
            merged[field] = values[selected]
            validated.setdefault("field_sources", {})[field] = [selected]
            selected_metadata = (
                sources[selected].get("financial_metric_metadata", {}).get(field, {})
                if isinstance(sources[selected].get("financial_metric_metadata"), dict)
                else {}
            )
            if field in conflicts:
                period_status = "CONFLICT"
            elif (
                not selected_metadata.get("period_type")
                or str(selected_metadata.get("period_type")).strip().upper()
                in {"UNSPECIFIED", "PROVIDER_REPORTED_UNSPECIFIED"}
                or not selected_metadata.get("period_end_date")
            ):
                period_status = "PERIOD_UNSPECIFIED"
            elif len(comparable_values) > 1:
                period_status = "RECONCILED"
            else:
                period_status = "SINGLE_SOURCE"
            observations[field] = {
                "selected_source": selected, "values": comparable_values,
                "observed_at": sources[selected].get("financial_data_observed_at"),
                "provider_period_end_timestamp": sources[selected].get("financial_period_end_timestamp"),
                "period_type": selected_metadata.get("period_type"),
                "period_end_date": selected_metadata.get("period_end_date"),
                "unit": selected_metadata.get(
                    "unit", "provider_financial_currency" if field == "fcf" else "percentage_points"
                ),
                "currency": selected_metadata.get("currency"),
                "period_status": period_status,
                "non_comparable_values": {
                    source: value for source, value in values.items() if source in excluded_sources
                },
                "source_metadata": {
                    source: data.get("financial_metric_metadata", {}).get(field, {})
                    for source, data in sources.items()
                    if isinstance(data.get("financial_metric_metadata"), dict)
                    and field in data["financial_metric_metadata"]
                },
                "non_comparable_reason": exclusion.get("reason"),
            }
        merged["financial_observations"] = observations
        metric_observations, exclusions = DataRefreshWorker._build_metric_observations(sources)
        merged["metric_observations"] = metric_observations
        merged["metric_observation_exclusions"] = exclusions
        merged.pop("financial_metric_metadata", None)

    @staticmethod
    def _build_metric_observations(sources: dict[str, dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, str]]]]:
        """Build canonical financial evidence only from explicit provider filing dates."""
        observations: dict[str, list[dict[str, Any]]] = {}
        exclusions: dict[str, list[dict[str, str]]] = {}
        for field in ("operating_margin_pct", "revenue_growth_pct"):
            evidence: list[dict[str, Any]] = []
            omitted: list[dict[str, str]] = []
            for source, data in sources.items():
                value = data.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                metadata_by_field = data.get("financial_metric_metadata")
                metadata = metadata_by_field.get(field) if isinstance(metadata_by_field, dict) else None
                metadata = metadata if isinstance(metadata, dict) else {}
                unit = metadata.get("unit")
                if unit in {"percentage_points", "%", "pct"}:
                    unit = "percent"
                period_type = str(metadata.get("period_type") or "").strip()
                period_start = metadata.get("period_start_date")
                period_end = metadata.get("period_end_date")
                reported_at = metadata.get("filed_at")
                observed_at = data.get("financial_data_observed_at")
                source_url = metadata.get("source_url") or data.get("source_url")
                fields = {
                    "reported_at": reported_at, "observed_at": observed_at,
                    "period_type": period_type, "period_start_date": period_start,
                    "period_end_date": period_end, "unit": unit, "source_url": source_url,
                }
                missing = [name for name, item in fields.items() if not item]
                if missing:
                    omitted.append({"source_id": str(source), "reason_code": "REQUIRED_EVIDENCE_FIELD_MISSING", "missing_fields": ",".join(missing)})
                    continue
                if unit != "percent":
                    omitted.append({"source_id": str(source), "reason_code": "UNSUPPORTED_METRIC_UNIT", "missing_fields": ""})
                    continue
                evidence.append({
                    "source_id": str(source), "value": float(value), "unit": "percent",
                    "currency": metadata.get("currency"),
                    "period": f"{period_type}:{period_start}/{period_end}",
                    "reported_at": str(reported_at), "observed_at": str(observed_at),
                    "source_url": str(source_url),
                })
            if evidence:
                observations[field] = evidence
            if omitted:
                exclusions[field] = omitted
        return observations, exclusions

    @staticmethod
    def _preferred_financial_source(values: dict[str, Any]) -> str:
        for source in ("stockanalysis.com", "yfinance", "finviz.com", "sec_edgar"):
            if source in values:
                return source
        return next(iter(values))

    @staticmethod
    def _yahoo_market_source(yahoo_data: dict[str, Any], history: dict[str, list] | None) -> dict[str, Any]:
        keys = (
            "ticker", "source", "quote_currency", "market_cap_currency", "market_cap",
            "exchange",
            "price_history", "volume_history", "price_history_dates",
            "price_history_basis",
            "levered_fcf", "operating_margin_pct", "revenue_growth_pct",
            "financial_metric_metadata",
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
