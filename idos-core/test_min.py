import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,
    'volume_avg': 525924,
}

# Replicate exact scan logic
cap = data.get('market_cap', 0)
dolvol = data.get('avg_dollar_volume', 0) or data.get('volume_avg', 0)
min_cap = 2e9
min_dolvol = 100e3
is_investable = cap >= min_cap and dolvol >= min_dolvol
print(f'Manual: cap={cap:.0f}, dolvol={dolvol:.0f}, investable={is_investable}')

# Now call actual scan
result = engine.scan('X', data)
print(f'Scan: investability={result.details["investability"]}, passed={result.passed}')