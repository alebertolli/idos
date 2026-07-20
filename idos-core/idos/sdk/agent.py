from typing import Any
from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus
from idos.events.types import Event
from idos.events.bus import get_event_bus


class AgentBase(BaseWorker):
    name: str = "agent"

    def on_start(self, context: dict[str, Any]):
        pass

    def on_event(self, event: Event):
        pass

    def on_complete(self, result: WorkerResult):
        pass

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        self.on_start(context)
        bus = get_event_bus()
        for event in bus.get_history():
            self.on_event(event)
        result_data = self.execute_agent_task(context)
        result = WorkerResult(
            status=WorkerStatus.SUCCESS,
            worker=self.name,
            output=result_data,
        )
        self.on_complete(result)
        return result_data

    def execute_agent_task(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def subscribe_to(self, event_type: str):
        bus = get_event_bus()
        bus.subscribe(event_type, lambda e: self.on_event(e))
