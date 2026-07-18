from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class InboxPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InboxStatus(StrEnum):
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class InboxItem:
    id: str
    title: str
    description: str = ""
    priority: InboxPriority = InboxPriority.MEDIUM
    status: InboxStatus = InboxStatus.PENDING
    source: str = ""
    ticker: str = ""
    response_deadline: str = ""
    resolution: str = ""
    created_at: str = ""
    resolved_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


class DecisionInbox:
    def __init__(self):
        self._items: dict[str, InboxItem] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"INBOX-{datetime.now(UTC).strftime('%Y%m%d')}-{self._counter:04d}"

    def add(self, title: str, description: str = "",
            priority: InboxPriority = InboxPriority.MEDIUM,
            source: str = "", ticker: str = "",
            response_deadline: str = "") -> InboxItem:
        item = InboxItem(
            id=self._next_id(),
            title=title,
            description=description,
            priority=priority,
            source=source,
            ticker=ticker,
            response_deadline=response_deadline,
        )
        self._items[item.id] = item
        return item

    def get(self, item_id: str) -> InboxItem | None:
        return self._items.get(item_id)

    def approve(self, item_id: str, resolution: str = ""):
        item = self.get(item_id)
        if item:
            item.status = InboxStatus.APPROVED
            item.resolution = resolution
            item.resolved_at = datetime.now(UTC).isoformat()

    def reject(self, item_id: str, resolution: str = ""):
        item = self.get(item_id)
        if item:
            item.status = InboxStatus.REJECTED
            item.resolution = resolution
            item.resolved_at = datetime.now(UTC).isoformat()

    def pending(self) -> list[InboxItem]:
        return [i for i in self._items.values() if i.status == InboxStatus.PENDING]

    def by_priority(self, priority: InboxPriority) -> list[InboxItem]:
        return [i for i in self._items.values() if i.priority == priority]

    def urgent(self) -> list[InboxItem]:
        return [i for i in self._items.values()
                if i.status == InboxStatus.PENDING and i.priority == InboxPriority.HIGH]

    def all(self) -> list[InboxItem]:
        return sorted(self._items.values(),
                      key=lambda i: (["HIGH", "MEDIUM", "LOW"].index(i.priority.value),
                                     i.created_at or ""))

    def count(self) -> int:
        return len(self._items)
