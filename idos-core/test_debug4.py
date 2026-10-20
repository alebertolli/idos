import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,
    'volume_avg': 525924,
}

result = engine.scan('TEST', data)

# Print ALL details
print(f"Full details dict: {result.details}")
print(f"investability field: {result.details.get('investability')}")
print(f"passed: {result.passed}")

# The scan method should have is_investable = cap >= min_cap and dolvol >= min_dolvol
# If investability is 0, then is_investable was False
# Let me check what cap and dolvol the scan method actually used
# by checking if there's something else modifying the data