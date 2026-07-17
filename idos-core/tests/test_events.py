from idos.events.bus import EventBus, get_event_bus
from idos.events.types import Event


def test_event_bus_singleton():
    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2


def test_publish_and_subscribe():
    bus = EventBus()
    received = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("test:event", handler)
    bus.publish_sync("test:event", {"key": "value"})
    assert len(received) == 1
    assert received[0].type == "test:event"
    assert received[0].data["key"] == "value"


def test_unsubscribe():
    bus = EventBus()
    received = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("test:event", handler)
    bus.unsubscribe("test:event", handler)
    bus.publish_sync("test:event")
    assert len(received) == 0


def test_event_history():
    bus = EventBus()
    bus.publish_sync("event:a", {})
    bus.publish_sync("event:b", {})
    bus.publish_sync("event:a", {})
    assert len(bus.get_history()) == 3
    assert len(bus.get_history("event:a")) == 2
    assert len(bus.get_history("event:b")) == 1
