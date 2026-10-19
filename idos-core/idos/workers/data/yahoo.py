from typing import Any, Optional
from datetime import datetime, timezone
import math

import yfinance as yf

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


class YahooFinanceWorker(BaseWorker):
    name = "yahoo_finance"

    @staticmethod
    def _percent_points(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) * 100 if math.isfinite(value) else None

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.timeout = self.config.get("timeout", 30)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        if not ticker:
            msg = "No ticker provided"
            raise ValueError(msg)

        period = context.get("period", "1y")
        stock = yf.Ticker(ticker)
        provider_errors: list[str] = []
        try:
            info = stock.info or {}
        except Exception as exc:
            # Yahoo's summary endpoint can fail independently of its price
            # history/fast_info endpoints. Keep gathering usable evidence and
            # report the failure so downstream quality gates remain auditable.
            info = {}
            provider_errors.append(f"info: {exc}")

        try:
            history = stock.history(period=period, auto_adjust=False)
        except Exception as exc:
            history = None
            provider_errors.append(f"history: {exc}")
        market_cap = info.get("marketCap")
        quote_currency = info.get("currency")
        exchange = info.get("exchange")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        # yfinance 1.x moved currency and market-cap access to fast_info. Its
        # market_cap is derived from share count x last price in quote currency.
        try:
            fast_info = stock.fast_info
        except Exception as exc:
            fast_info = {}
            provider_errors.append(f"fast_info: {exc}")

        fast_market_cap = self._fast_info_value(fast_info, "market_cap", provider_errors)
        quote_currency = quote_currency or self._fast_info_value(fast_info, "currency", provider_errors)
        exchange = exchange or self._fast_info_value(fast_info, "exchange", provider_errors)
        price = price or self._fast_info_value(fast_info, "last_price", provider_errors)
        market_cap = fast_market_cap or market_cap

        data: dict[str, Any] = {
            "ticker": ticker,
            "source": "yahoo_finance",
            "price": price,
            "market_cap": market_cap,
            "market_cap_currency": quote_currency if market_cap is not None else None,
            "quote_currency": quote_currency,
            "exchange": exchange,
            "enterprise_value": info.get("enterpriseValue"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "pb_ratio": info.get("priceToBook"),
            "ps_ratio": info.get("priceToSalesTrailing12Months"),
            "p_fcf_ratio": info.get("priceToFreeCashFlow"),
            "eps_ttm": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "revenue_ttm": info.get("totalRevenue"),
            "revenue_growth_pct": self._percent_points(info.get("revenueGrowth")),
            "gross_margin_pct": info.get("grossMargins"),
            "operating_margin_pct": self._percent_points(info.get("operatingMargins")),
            "net_margin_pct": info.get("profitMargins"),
            "roa_pct": info.get("returnOnAssets"),
            "roe_pct": info.get("returnOnEquity"),
            "roic_pct": info.get("returnOnCapital"),
            "debt_equity_ratio": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "dividend_yield_pct": info.get("dividendYield"),
            "beta_5y": info.get("beta"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "fcf": info.get("freeCashflow"),
            "financial_currency": info.get("financialCurrency"),
            "financial_data_observed_at": datetime.now(timezone.utc).isoformat(),
            "financial_period_end_timestamp": info.get("mostRecentQuarter"),
            "operating_cf": info.get("operatingCashFlow"),
            "high_52w": info.get("fiftyTwoWeekHigh"),
            "low_52w": info.get("fiftyTwoWeekLow"),
            "ma_50d": info.get("fiftyDayAverage"),
            "ma_200d": info.get("twoHundredDayAverage"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "employees": info.get("fullTimeEmployees"),
            "price_target_avg": info.get("targetMeanPrice"),
            "price_target_low": info.get("targetLowPrice"),
            "price_target_high": info.get("targetHighPrice"),
            "analyst_count": info.get("numberOfAnalystOpinions"),
            "next_earnings_date": info.get("earningsTimestamp"),
        }

        if history is not None and not history.empty:
            prices = history["Close"].tolist()
            volumes = history["Volume"].tolist()
            data["price_history"] = prices
            data["volume_history"] = volumes
            data["price_history_dates"] = [str(d.date()) for d in history.index]
            data["price_history_basis"] = "close_unadjusted"
            data["avg_volume"] = sum(volumes) / len(volumes) if volumes else 0
            data["price_change_1m"] = (
                ((prices[-1] - prices[-21]) / prices[-21] * 100)
                if len(prices) > 21
                else None
            )
            data["price_change_3m"] = (
                ((prices[-1] - prices[-63]) / prices[-63] * 100)
                if len(prices) > 63
                else None
            )
            data["price_change_6m"] = (
                ((prices[-1] - prices[-126]) / prices[-126] * 100)
                if len(prices) > 126
                else None
            )
            data["price_change_12m"] = (
                ((prices[-1] - prices[-252]) / prices[-252] * 100)
                if len(prices) > 252
                else None
            )

        if provider_errors:
            data["provider_errors"] = provider_errors

        data = {k: v for k, v in data.items() if v is not None}
        return data

    @staticmethod
    def _fast_info_value(fast_info: Any, key: str, errors: list[str]) -> Any:
        """Read one lazy fast_info field without losing unrelated Yahoo data."""
        try:
            getter = getattr(fast_info, "get", None)
            return getter(key) if callable(getter) else fast_info[key]
        except Exception as exc:
            errors.append(f"fast_info.{key}: {exc}")
            return None
