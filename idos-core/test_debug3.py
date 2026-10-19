import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# Test: Make sure volume_avg is KEPT, not popped
data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,  # Will be overridden by fallback
    'volume_avg': 525924,    # Keep this field
    'relative_strength_3m': 70,
    'relative_strength_12m': 70,
    'price_volume_trend': 5,
    'roic': 15,
    'fcf_yield': 0.05,
    'debt_to_equity': 0.3
}

# Check what the scan method sees
dolvol = data.get("avg_dollar_volume", 0) or data.get("volume_avg", 0)
print(f"dolvol from data.get logic: ${dolvol:,.0f}")

result = engine.scan('TEST', data)
print(f"Scan result - investability: {result.details['investability']}")
print(f"Scan result - passed: {result.passed}")