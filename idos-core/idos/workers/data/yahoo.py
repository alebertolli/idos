from typing import Any, Optional
from datetime import datetime, timezone

import yfinance as yf

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


class YahooFinanceWorker(BaseWorker):
    name = "yahoo_finance"

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

        info = stock.info or {}
        history = stock.history(period=period, auto_adjust=False)
        market_cap = info.get("marketCap")
        quote_currency = info.get("currency")
        exchange = info.get("exchange")
        # yfinance 1.x moved currency and market-cap access to fast_info. Its
        # market_cap is derived from share count x last price in quote currency.
        try:
            fast_info = stock.fast_info
            quote_currency = quote_currency or fast_info["currency"]
            exchange = exchange or fast_info["exchange"]
            market_cap = fast_info["market_cap"] or market_cap
        except Exception:
            pass

        data: dict[str, Any] = {
            "ticker": ticker,
            "source": "yahoo_finance",
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": market_cap,
            "market_cap_currency": quote_currency if market_cap is not None else None,
            # Yahoo may expose fund net assets but does not always supply an
            # observation date. Keep the date absent unless source metadata
            # explicitly provides one; the global ETF gate then fails closed.
            "aum": info.get("totalAssets"),
            "aum_currency": quote_currency if info.get("totalAssets") is not None else None,
            "aum_as_of": self._source_date(info.get("aumAsOfDate") or info.get("totalAssetsDate")),
            "aum_source": "yfinance",
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
            "revenue_growth_pct": info.get("revenueGrowth"),
            "gross_margin_pct": info.get("grossMargins"),
            "operating_margin_pct": info.get("operatingMargins"),
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

        if not history.empty:
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

        data = {k: v for k, v in data.items() if v is not None}
        return data

    @staticmethod
    def _source_date(value: Any) -> str | None:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value[:10]).date().isoformat()
            except ValueError:
                return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                return None
        return None
