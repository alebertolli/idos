import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# Store original scan
original_scan = engine.scan

def debug_scan(ticker, data):
    # Print the data being received
    avg_dol = data.get('avg_dollar_volume', 'NOT SET')
    vol_avg = data.get('volume_avg', 'NOT SET')
    print(f'Data received: avg_dollar_volume={avg_dol}, volume_avg={vol_avg}')
    result = original_scan(ticker, data)
    print(f'Result investability: {result.details["investability"]}')
    return result

engine.scan = debug_scan

data = {
    'market_cap': 81.86e9,
    'avg_dollar_volume': 0,
    'volume_avg': 525924,
}

result = engine.scan('TEST', data)
print(f'Final investability: {result.details["investability"]}')