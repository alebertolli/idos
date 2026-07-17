from datetime import datetime
from typing import Any
from idos.data.sqlite import SQLiteStore


class Tracer:
    _instance: "Tracer | None" = None

    def __init__(self):
        self._store: SQLiteStore | None = None
        self._current_run_id: str = ""

    def configure(self, store: SQLiteStore):
        self._store = store

    def start_run(self, worker: str) -> str:
        run_id = f"RUN-{datetime.now(datetime.UTC).strftime('%Y%m%d-%H%M%S')}-{worker}"
        self._current_run_id = run_id
        return run_id

    def trace(self, step: str, status: str, worker: str = "",
              provider: str = "", prompt_id: str = "", tokens_in: int = 0,
              tokens_out: int = 0, latency_ms: int = 0, detail: str = ""):
        if self._store is None:
            return
        self._store.trace(
            run_id=self._current_run_id,
            worker=worker or self._current_run_id.split("-")[-1],
            step=step,
            status=status,
            provider=provider,
            prompt_id=prompt_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            detail=detail,
        )


def get_tracer() -> Tracer:
    if Tracer._instance is None:
        Tracer._instance = Tracer()
    return Tracer._instance
