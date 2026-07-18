"""Step 6: Scout Worker"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.workers.data.scout_worker import ScoutWorker

uw = Path("idos-config/universe/watchlist.md")
worker = ScoutWorker({
    "universe_path": str(uw),
    "min_score": 50,
})

result = worker.execute({
    "tickers": ["GOOGL"],
    "refresh_data": False,
})

print(f"Status: {result.status}")
print(f"Full output: {result.output}")

if result.status == "success":
    screened = result.output.get("results", result.output.get("screened", []))
    print(f"Tickers screened: {len(screened)}")
    for r in screened:
        if isinstance(r, dict):
            print(f"  {r.get('ticker','?')}: score={r.get('score','?')}, passed={r.get('passed','?')}")
else:
    print(f"Error: {result.error}")

print("\nSTEP 6 COMPLETE")
