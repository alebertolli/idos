import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,
    'volume_avg': 525924,
    'relative_strength_3m': 70,
    'relative_strength_12m': 70,
    'price_volume_trend': 5,
    'roic': 15,
    'fcf_yield': 0.05,
    'debt_to_equity': 0.3
}

# Print the keys and values that the scout will see
print(f"data keys: {list(data.keys())}")
print(f"avg_dollar_volume: {data.get('avg_dollar_volume')}")
print(f"volume_avg: {data.get('volume_avg')}")
print(f"avg_volume: {data.get('avg_volume', 'NOT SET')}")

# Replicate the scout's logic exactly
dolvol_raw = data.get('avg_dollar_volume', 0) or data.get('volume_avg', 0) or data.get('avg_volume', 0)
print(f'dolvol_raw from logic: {dolvol_raw}')

result = engine.scan('TEST', data)
inv = result.details['investability']
print(f'Scout investability: {inv}')
print(f'Scout passed: {result.passed}')