from typing import Any
import yfinance as yf


class PriceProvider:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def get_price(self, ticker: str) -> dict[str, Any]:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        history = stock.history(period="1mo")
        prices = []
        for date, row in history.iterrows():
            prices.append({
                "date": date.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return {
            "ticker": ticker.upper(),
            "source": "yahoo_finance",
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "target_mean": info.get("targetMeanPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "book_value": info.get("bookValue"),
            "revenue": info.get("totalRevenue"),
            "ebitda": info.get("ebitda"),
            "prices": prices,
        }

    def get_history(self, ticker: str, period: str = "1y") -> list[dict[str, Any]]:
        stock = yf.Ticker(ticker)
        history = stock.history(period=period)
        return [
            {
                "date": date.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            }
            for date, row in history.iterrows()
        ]
