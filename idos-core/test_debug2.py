import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# Minimal test case
data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,  # Set to 0
    'volume_avg': 525924,    # Legacy field
    'relative_strength_3m': 70,
    'relative_strength_12m': 70,
    'price_volume_trend': 5,
    'roic': 15,
    'fcf_yield': 0.05,
    'debt_to_equity': 0.3
}

# Manually replicate the scan's investability logic
cap = data.get("market_cap", 0)
dolvol = data.get("avg_dollar_volume", 0) or data.get("volume_avg", 0)
min_cap = 2e9
min_dolvol = 100e3
is_investable = cap >= min_cap and dolvol >= min_dolvol

print(f"cap from data: ${cap:,.0f}")
print(f"avg_dollar_volume from data.get: {data.get('avg_dollar_volume', 0)}")
print(f"volume_avg from data.get: {data.get('volume_avg', 0)}")
print(f"dolvol computed: ${dolvol:,.0f}")
print(f"is_investable: {is_investable}")

# Now try the actual scan
result = engine.scan('TEST', data)
print(f"\nActual scan result:")
print(f"  investability={result.details['investability']}")
print(f"  passed={result.passed}")