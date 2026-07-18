"""Step 13: Scheduler"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.workers.base import BaseWorker
from idos.workers.scheduler.service import SchedulerService, ScheduledJob

class E2ETestWorker(BaseWorker):
    name = "test_e2e"
    def run(self, context):
        return {"result": "ok", "ticker": context.get("ticker")}

print("="*60, "\nSTEP 13: Scheduler")

s = SchedulerService()
s.register(ScheduledJob("test_e2e", E2ETestWorker(), "minutes", 1,
                         context={"ticker": "GOOGL"}))
status = s.job_status()
print(f"  Registered jobs: {list(status.keys())}")

job = s._jobs["test_e2e"]
result = job.run()
print(f"  Manual run status: {result.status}")
print(f"  Manual run output: {result.output}")
assert result.status == "success"
assert result.output["ticker"] == "GOOGL"

s.register(ScheduledJob("daily", E2ETestWorker(), "days", 1, at_time="09:00"))
s.register(ScheduledJob("weekly", E2ETestWorker(), "monday", at_time="09:00"))
s.register(ScheduledJob("friday", E2ETestWorker(), "friday", at_time="17:00"))
print(f"  All jobs: {list(s.job_status().keys())}")
assert len(s.job_status()) == 4

print("\nSTEP 13 COMPLETE")
