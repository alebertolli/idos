from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


class SuccessWorker(BaseWorker):
    name = "test_success"

    def run(self, context):
        return {"result": "ok", "ticker": context.get("ticker")}


class FailingWorker(BaseWorker):
    name = "test_fail"

    def run(self, context):
        raise ValueError("Something broke")


def test_success_worker():
    worker = SuccessWorker()
    result = worker.execute({"ticker": "MELI"})
    assert result.status == WorkerStatus.SUCCESS
    assert result.output["result"] == "ok"
    assert result.output["ticker"] == "MELI"
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.elapsed_seconds >= 0


def test_failing_worker():
    worker = FailingWorker()
    result = worker.execute({})
    assert result.status == WorkerStatus.FAILED
    assert "Something broke" in result.error


def test_worker_result_elapsed():
    from datetime import datetime, timezone, timedelta
    r = WorkerResult(
        status=WorkerStatus.SUCCESS,
        worker="test",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        completed_at=datetime.now(timezone.utc),
    )
    assert 4.5 <= r.elapsed_seconds <= 5.5


def test_base_worker_custom_config():
    worker = SuccessWorker({"api_key": "test"})
    assert worker.config["api_key"] == "test"
