"""Step 14: Digest Worker"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.workers.data.digest_worker import DigestWorker

print("="*60, "\nSTEP 14: Digest Worker")

w = DigestWorker()
result = w.execute({
    "scout_results": [
        {"ticker": "GOOGL", "passed": True, "score": 85, "reason": "Moat digital, calidad"},
        {"ticker": "MELI", "passed": True, "score": 78, "reason": "Crecimiento LatAm"},
    ],
    "risk_alerts": [],
    "opportunities": [
        {"id": "OPP-001", "ticker": "GOOGL", "status": "WATCHLIST", "conviction": 75},
    ],
})

print(f"  Lines: {result.output['line_count']}")
print(f"  Summary: {result.output['summary']}")
digest_clean = result.output['digest'].replace('\U0001f4ca','').replace('\U0001f534','').replace('\U0001f7e1','').replace('\U0001f7e2','')
print(f"\n  Digest preview:\n{digest_clean[:600]}...")

assert result.status == "success"
assert "GOOGL" in result.output["digest"]
assert result.output["summary"]["opportunities"] == 2

print("\nSTEP 14 COMPLETE")
