"""Step 12: Data Workers (stockanalysis, yfinance, cache, validator)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.workers.data.stockanalysis import StockAnalysisWorker
from idos.workers.data.yahoo import YahooFinanceWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.validator import DataValidator

ticker = "GOOGL"

print("="*60, "\nSTEP 12a: StockAnalysis Worker")
sa = StockAnalysisWorker()
result = sa.execute({"ticker": ticker})
print(f"  Status: {result.status}")
if result.status == "success":
    print(f"  Market Cap: {result.output.get('market_cap', 'N/A')}")
    print(f"  PE Ratio: {result.output.get('pe_ratio_ttm', 'N/A')}")
    print(f"  ROIC: {result.output.get('roic_pct', 'N/A')}")
else:
    print(f"  Note: {result.error}")

print("\n" + "="*60, "\nSTEP 12b: YahooFinance Worker")
yf = YahooFinanceWorker()
result2 = yf.execute({"ticker": ticker, "period": "1y"})
print(f"  Status: {result2.status}")
if result2.status == "success":
    print(f"  Price: {result2.output.get('price', 'N/A')}")
    print(f"  Market Cap: {result2.output.get('market_cap', 'N/A')}")
    print(f"  Change 3m: {result2.output.get('price_change_3m', 'N/A')}%")
    print(f"  Sector: {result2.output.get('sector', 'N/A')}")

print("\n" + "="*60, "\nSTEP 12c: Cache")
cache = DataCache()
cache.set(f"test:{ticker}", {"pe": 25.0, "ticker": ticker}, source="test", ttl_seconds=60)
cached = cache.get(f"test:{ticker}")
print(f"  Cached: {'YES' if cached else 'NO'}")
if cached:
    print(f"  Data: {cached}")

print("\n" + "="*60, "\nSTEP 12d: DataValidator")
v = DataValidator()
validation = v.cross_validate({
    "stockanalysis.com": {"pe_ratio": 25.0, "market_cap": 2_000_000_000_000, "ticker": ticker},
    "yfinance": {"pe_ratio": 24.5, "market_cap": 2_050_000_000_000, "ticker": ticker},
})
print(f"  Sources: {validation['sources_used']}")
print(f"  Conflicts: {len(validation['conflicts'])}")
print(f"  Merged PE: {validation['merged_data'].get('pe_ratio', 'N/A')}")

warnings = v.validate_metrics({"debt_equity_ratio": 0.1, "current_ratio": 2.5, "operating_margin_pct": 30})
print(f"  Warnings for clean company: {len(warnings)} (expected 0)")

print("\n" + "="*60)
print("STEP 12 COMPLETE")
