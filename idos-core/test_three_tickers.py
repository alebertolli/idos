import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# RACE data from cache: market_cap=81.86B, volume_avg=525924
# NVDA: typically large cap, high volume
# MELI: MercadoLibre, also large cap

# Test 1: RACE - using volume_avg fallback
data_race = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,  # Will be overridden by fallback
    'volume_avg': 525924,    # Legacy field - triggers fallback
    'relative_strength_3m': 70,
    'relative_strength_12m': 70,
    'price_volume_trend': 5,
    'roic': 15,
    'fcf_yield': 0.05,
    'debt_to_equity': 0.3
}

# Test 2: NVDA - large cap with high volume
data_nvda = {
    'market_cap': 1e12,  # ~$1T
    'avg_dollar_volume': 40e6,  # High volume directly
    'relative_strength_3m': 85,
    'relative_strength_12m': 80,
    'price_volume_trend': 8,
    'roic': 25,
    'fcf_yield': 0.02,
    'debt_to_equity': 0.1
}

# Test 3: MELI - MercadoLibre, large cap
data_meli = {
    'market_cap': 80e9,  # ~$80B
    'avg_dollar_volume': 3e6,  # Moderate volume directly
    'relative_strength_3m': 75,
    'relative_strength_12m': 72,
    'price_volume_trend': 5,
    'roic': 20,
    'fcf_yield': 0.01,
    'debt_to_equity': 0.5
}

print("=" * 60)
print("Testing RACE, NVDA, MELI with min_score=70")
print("=" * 60)

# Test RACE with volume_avg fallback
result_race = engine.scan('RACE', data_race)
print(f"RACE: score={result_race.score}, passed={result_race.passed}")
print(f"  investability={result_race.details['investability']}")
print(f"  flags={result_race.flags}")

# Test NVDA
result_nvda = engine.scan('NVDA', data_nvda)
print(f"NVDA: score={result_nvda.score}, passed={result_nvda.passed}")
print(f"  investability={result_nvda.details['investability']}")
print(f"  flags={result_nvda.flags}")

# Test MELI
result_meli = engine.scan('MELI', data_meli)
print(f"MELI: score={result_meli.score}, passed={result_meli.passed}")
print(f"  investability={result_meli.details['investability']}")
print(f"  flags={result_meli.flags}")