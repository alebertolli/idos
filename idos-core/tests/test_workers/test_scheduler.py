from idos.workers.base import BaseWorker
from idos.workers.scheduler.service import SchedulerService, ScheduledJob


class DummyWorker(BaseWorker):
    name = "dummy"

    def run(self, context):
        return {"done": True, "input": context}


def test_scheduler_register():
    s = SchedulerService()
    w = DummyWorker()
    job = ScheduledJob("test_job", w, "minutes", 5)
    s.register(job)
    assert "test_job" in s._jobs
    assert s._jobs["test_job"].interval_value == 5


def test_scheduler_unregister():
    s = SchedulerService()
    w = DummyWorker()
    job = ScheduledJob("remove_me", w, "hours", 1)
    s.register(job)
    s.unregister("remove_me")
    assert "remove_me" not in s._jobs


def test_scheduler_job_status_empty():
    s = SchedulerService()
    assert s.job_status() == {}


def test_scheduler_job_status():
    s = SchedulerService()
    w = DummyWorker()
    s.register(ScheduledJob("j1", w, "minutes", 10))
    s.register(ScheduledJob("j2", w, "days", 1, at_time="09:00"))
    status = s.job_status()
    assert "j1" in status
    assert "j2" in status
    assert status["j1"]["runs"] == 0


def test_scheduled_job_run():
    w = DummyWorker()
    job = ScheduledJob("test", w, "minutes", 1, context={"ticker": "MELI"})
    result = job.run()
    assert result.status == "success"
    assert result.output["done"] is True
    assert result.output["input"]["ticker"] == "MELI"
    assert job.runs_count == 1


def test_scheduled_job_tracks_failures():
    class FailWorker(BaseWorker):
        name = "fail"

        def run(self, context):
            raise ValueError("fail")

    w = FailWorker()
    job = ScheduledJob("fail_job", w, "minutes", 1)
    job.run()
    assert job.failures_count == 1


def test_scheduler_multiple_jobs():
    s = SchedulerService()
    w = DummyWorker()
    s.register(ScheduledJob("a", w, "minutes", 1))
    s.register(ScheduledJob("b", w, "hours", 2))
    s.register(ScheduledJob("c", w, "days", 1, at_time="10:00"))
    s.register(ScheduledJob("d", w, "monday", at_time="09:00"))
    s.register(ScheduledJob("e", w, "friday", at_time="17:00"))
    assert len(s._jobs) == 5
