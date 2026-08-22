import sys
sys.path.insert(0, '.')
from idos.discovery.scout import ScoutEngine

engine = ScoutEngine(min_score=70)

# Test just the dollar volume logic
cap = 81.86e9
dolvol_from_avg = 525924  # from volume_avg
dolvol_direct = 0  # not set

# The scout's logic: metrics.get("avg_dollar_volume", 0) or metrics.get("volume_avg", 0)
dolvol = dolvol_from_avg if dolvol_from_avg else dolvol_direct

print(f"cap = ${cap:,.0f}")
print(f"dolvol_from_avg = ${dolvol_from_avg:,.0f}")
print(f"dolvol_direct = ${dolvol_direct:,.0f}")
print(f"dolvol (after fallback) = ${dolvol:,.0f}")
print(f"min_dolvol = ${100e3:,.0f}")
print(f"cap >= min_cap: {cap >= 2e9}")
print(f"dolvol >= min_dolvol: {dolvol >= 100e3}")
print(f"is_investable = {cap >= 2e9 and dolvol >= 100e3}")