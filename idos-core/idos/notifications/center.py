from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.timezone import AR_TZ

class NotificationPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

@dataclass
class Notification:
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.LOW
    channel: str = "dashboard"
    source: str = "system"
    timestamp: datetime = field(default_factory=lambda: datetime.now(AR_TZ))
    metadata: dict[str, Any] = field(default_factory=dict)

class NotificationCenter:
    _instance: "NotificationCenter | None" = None

    def __init__(self):
        self._inbox: list[Notification] = []

    @property
    def inbox(self) -> list[Notification]:
        return sorted(self._inbox, key=lambda n: n.timestamp, reverse=True)

    def notify(self, notification: Notification):
        self._inbox.append(notification)

    def get_pending(self) -> list[Notification]:
        return [n for n in self._inbox if n.priority == NotificationPriority.HIGH]

    def get_by_source(self, source: str) -> list[Notification]:
        return [n for n in self._inbox if n.source == source]

    def clear(self):
        self._inbox.clear()

def get_notification_center() -> NotificationCenter:
    if NotificationCenter._instance is None:
        NotificationCenter._instance = NotificationCenter()
    return NotificationCenter._instance
