import sys
sys.path.insert(0, r'C:\REPOS\idos\idos-core')
from ids.discovery.scout import ScoutEngine, ScoutResult

# Test 1: Basic engine instantiation
engine = ScoutEngine(min_score=70)
print(f"Engine min_score: {engine.min_score}")

# Test 2: Investability filter - high market cap + high dollar volume
data1 = {
    'metrics': {
        'market_cap': 5e9,
        'avg_dollar_volume': 500e3,
        'relative_strength_3m': 80,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 0.18,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.4,
    }
}
result1 = engine.scan('TEST', data1)
print(f"\nTest 1 - High cap/high vol:")
print(f"  score: {result1.score}")
print(f"  passed: {result1.passed}")
print(f"  discovery_type: {result1.discovery_type}")
print(f"  flags: {result1.flags}")
print(f"  reason: {result1.reason}")
print(f"  details: {result1.details}")

# Test 3: Low dollar volume (fails investability)
data2 = {
    'metrics': {
        'market_cap': 5e9,
        'avg_dollar_volume': 10e3,  # too low
        'relative_strength_3m': 80,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 0.18,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.4,
    }
}
result2 = engine.scan('TEST', data2)
print(f"\nTest 2 - High cap/low vol (should fail investability):")
print(f"  score: {result2.score}")
print(f"  passed: {result2.passed}")
print(f"  discovery_type: {result2.discovery_type}")
print(f"  flags: {result2.flags}")
print(f"  reason: {result2.reason}")
print(f"  details: {result2.details}")

# Test 4: Low market cap (fails investability)
data3 = {
    'metrics': {
        'market_cap': 500e6,  # too low
        'avg_dollar_volume': 500e3,
        'relative_strength_3m': 80,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 0.18,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.4,
    }
}
result3 = engine.scan('TEST', data3)
print(f"\nTest 3 - Low cap/high vol (should fail investability):")
print(f"  score: {result3.score}")
print(f"  passed: {result3.passed}")
print(f"  discovery_type: {result3.discovery_type}")
print(f"  flags: {result3.flags}")
print(f"  reason: {result3.reason}")
print(f"  details: {result3.details}")

# Test 5: volume_avg legacy field name
data4 = {
    'metrics': {
        'market_cap': 5e9,
        'volume_avg': 500e3,  # legacy field name
        'relative_strength_3m': 80,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 0.18,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.4,
    }
}
result4 = engine.scan('TEST', data4)
print(f"\nTest 4 - volume_avg legacy field:")
print(f"  score: {result4.score}")
print(f"  passed: {result4.passed}")
print(f"  flags: {result4.flags}")
print(f"  reason: {result4.reason}")

# Test 6: avg_volume pipeline field name
data5 = {
    'metrics': {
        'market_cap': 5e9,
        'avg_volume': 500e3,  # pipeline field name
        'relative_strength_3m': 80,
        'relative_strength_12m': 70,
        'price_volume_trend': 5,
        'roic': 0.18,
        'fcf_yield': 0.05,
        'debt_to_equity': 0.4,
    }
}
result5 = engine.scan('TEST', data5)
print(f"\nTest 5 - avg_volume pipeline field:")
print(f"  score: {result5.score}")
print(f"  passed: {result5.passed}")
print(f"  flags: {result5.flags}")
print(f"  reason: {result5.reason}")

# Test 7: Score just above threshold
data6 = {
    'metrics': {
        'market_cap': 5e9,
        'avg_dollar_volume': 500e3,
        'relative_strength_3m': 60,
        'relative_strength_12m': 50,
        'price_volume_trend': 0,
        'roic': 0.12,
        'fcf_yield': 0.03,
        'debt_to_equity': 0.8,
    }
}
result6 = engine.scan('TEST', data6)
print(f"\nTest 6 - Borderline score ({engine.min_score} threshold):")
print(f"  score: {result6.score}")
print(f"  passed: {result6.passed}")
print(f"  discovery_type: {result6.discovery_type}")
print(f"  flags: {result6.flags}")
print(f"  reason: {result6.reason}")
print(f"  details: {result6.details}")