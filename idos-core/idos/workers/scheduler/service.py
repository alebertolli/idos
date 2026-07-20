import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

import schedule

from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class ScheduledJob:
    def __init__(
        self,
        name: str,
        worker: BaseWorker,
        interval_type: str,
        interval_value: int = 1,
        at_time: str = "",
        context: dict[str, Any] | None = None,
    ):
        self.name = name
        self.worker = worker
        self.interval_type = interval_type
        self.interval_value = interval_value
        self.at_time = at_time
        self.context = context or {}
        self.last_run: Optional[datetime] = None
        self.last_result: Optional[Any] = None
        self.runs_count = 0
        self.failures_count = 0

    def run(self):
        self.last_run = datetime.now(AR_TZ)
        result = self.worker.execute(self.context)
        self.last_result = result
        self.runs_count += 1
        if result.status == "failed":
            self.failures_count += 1
        return result

class SchedulerService:
    def __init__(self):
        self._jobs: dict[str, ScheduledJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register(self, job: ScheduledJob):
        self._jobs[job.name] = job
        if job.interval_type == "minutes":
            schedule.every(job.interval_value).minutes.do(job.run)
        elif job.interval_type == "hours":
            schedule.every(job.interval_value).hours.do(job.run)
        elif job.interval_type == "days":
            s = schedule.every(job.interval_value).days
            if job.at_time:
                s.at(job.at_time).do(job.run)
            else:
                s.do(job.run)
        elif job.interval_type == "weeks":
            s = schedule.every(job.interval_value).weeks
            if job.at_time:
                s.at(job.at_time).do(job.run)
            else:
                s.do(job.run)
        elif job.interval_type == "monday":
            schedule.every().monday.at(job.at_time or "09:00").do(job.run)
        elif job.interval_type == "friday":
            schedule.every().friday.at(job.at_time or "17:00").do(job.run)
        elif job.interval_type == "months":
            schedule.every(job.interval_value * 30).days.at(job.at_time or "09:00").do(job.run)
        elif job.interval_type == "quarterly":
            schedule.every(90).days.at(job.at_time or "09:00").do(job.run)
        elif job.interval_type == "semiannual":
            schedule.every(180).days.at(job.at_time or "09:00").do(job.run)

    def unregister(self, name: str):
        self._jobs.pop(name, None)
        schedule.clear(name)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def job_status(self) -> dict[str, Any]:
        return {
            name: {
                "last_run": str(j.last_run) if j.last_run else None,
                "runs": j.runs_count,
                "failures": j.failures_count,
                "has_last_result": j.last_result is not None,
            }
            for name, j in self._jobs.items()
        }

    def _run_loop(self):
        while self._running:
            schedule.run_pending()
            time.sleep(30)
