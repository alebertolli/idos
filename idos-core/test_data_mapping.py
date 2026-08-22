import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# Test 1: RACE with volume_avg only (no avg_dollar_volume) - tests the fallback
data1 = {
    'metrics': {
        'market_cap': 81.86e9,  # RACE's market cap
        'avg_dollar_volume': 0,  # Not set
        'volume_avg': 525924,    # Legacy field - should trigger fallback
        'relative_strength_3m': 70,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 15,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.3
    }
}

# Test 2: RACE with avg_dollar_volume set properly
data2 = {
    'metrics': {
        'market_cap': 81.86e9,
        'avg_dollar_volume': 525924,  # Set properly
        'relative_strength_3m': 70,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 15,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.3
    }
}

# Test 3: Small cap that should fail
data3 = {
    'metrics': {
        'market_cap': 500e6,   # $500M - below $2B minimum
        'avg_dollar_volume': 5e6,  # $5M - above $100K minimum
        'relative_strength_3m': 70,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 15,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.3
    }
}

result1 = engine.scan('RACE_fallback', data1)
result2 = engine.scan('RACE_proper', data2)
result3 = engine.scan('SMALL_cap', data3)

print(f'Test 1 - RACE with volume_avg fallback:')
print(f'  investability={result1.details["investability"]}, passed={result1.passed}')

print(f'Test 2 - RACE with avg_dollar_volume:')
print(f'  investability={result2.details["investability"]}, passed={result2.passed}')

print(f'Test 3 - Small cap (below market cap minimum):')
print(f'  investability={result3.details["investability"]}, passed={result3.passed}')
print(f'  Market cap: ${500e9:,.0f} vs minimum ${2e9:,.0f}')