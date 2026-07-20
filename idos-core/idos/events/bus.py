from collections import defaultdict
from typing import Any
from idos.events.types import Event, EventHandler
import asyncio
import logging

logger = logging.getLogger(__name__)


class EventBus:
    _instance: "EventBus | None" = None

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[Event] = []

    def subscribe(self, event_type: str, handler: EventHandler):
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler):
        if handler in self._handlers.get(event_type, []):
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event):
        self._history.append(event)
        for handler in self._handlers.get(event.type, []):
            try:
                result = handler(event)
                if result is not None:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        asyncio.run(result)
            except Exception as e:
                logger.exception("Handler %s failed for event %s: %s", handler.__name__, event.type, e)

    def publish_sync(self, event_type: str, data: dict[str, Any] | None = None, source: str = "system"):
        self.publish(Event(type=event_type, data=data or {}, source=source))

    def get_history(self, event_type: str | None = None) -> list[Event]:
        if event_type:
            return [e for e in self._history if e.type == event_type]
        return self._history.copy()

    def clear(self):
        self._handlers.clear()
        self._history.clear()


def get_event_bus() -> EventBus:
    if EventBus._instance is None:
        EventBus._instance = EventBus()
    return EventBus._instance
