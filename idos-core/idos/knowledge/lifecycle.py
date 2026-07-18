from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class KnowledgeStatus(StrEnum):
    CREATED = "CREATED"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    UPDATED = "UPDATED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


@dataclass
class KnowledgeObject:
    object_id: str
    object_type: str
    ticker: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    status: KnowledgeStatus = KnowledgeStatus.CREATED
    freshness: str = ""
    confidence: float = 0.0
    last_review: str = ""
    owner: str = "system"
    source_count: int = 0
    review_frequency_days: int = 90
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(UTC).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.freshness:
            self.freshness = now
        if not self.last_review:
            self.last_review = now

    def needs_review(self) -> bool:
        if not self.last_review:
            return True
        try:
            last = datetime.fromisoformat(self.last_review)
            delta = datetime.now(UTC) - last
            return delta.days >= self.review_frequency_days
        except (ValueError, TypeError):
            return True

    def promote(self, target: KnowledgeStatus):
        order = [KnowledgeStatus.CREATED, KnowledgeStatus.VERIFIED,
                 KnowledgeStatus.PUBLISHED, KnowledgeStatus.UPDATED,
                 KnowledgeStatus.DEPRECATED, KnowledgeStatus.ARCHIVED]
        if self.status in order and target in order:
            if order.index(target) >= order.index(self.status):
                self.status = target
                self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "ticker": self.ticker,
            "content": self.content,
            "status": self.status.value,
            "freshness": self.freshness,
            "confidence": self.confidence,
            "last_review": self.last_review,
            "owner": self.owner,
            "source_count": self.source_count,
            "review_frequency_days": self.review_frequency_days,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class KnowledgeLifecycle:
    def __init__(self):
        self._objects: dict[str, KnowledgeObject] = {}

    def register(self, obj: KnowledgeObject):
        self._objects[obj.object_id] = obj

    def get(self, object_id: str) -> KnowledgeObject | None:
        return self._objects.get(object_id)

    def promote_to(self, object_id: str, target: KnowledgeStatus) -> bool:
        obj = self.get(object_id)
        if obj:
            obj.promote(target)
            return True
        return False

    def verify(self, object_id: str):
        self.promote_to(object_id, KnowledgeStatus.VERIFIED)

    def publish(self, object_id: str):
        self.promote_to(object_id, KnowledgeStatus.PUBLISHED)

    def deprecate(self, object_id: str):
        self.promote_to(object_id, KnowledgeStatus.DEPRECATED)

    def archive(self, object_id: str):
        self.promote_to(object_id, KnowledgeStatus.ARCHIVED)

    def objects_needing_review(self) -> list[KnowledgeObject]:
        return [o for o in self._objects.values() if o.needs_review()]

    def by_ticker(self, ticker: str) -> list[KnowledgeObject]:
        return [o for o in self._objects.values() if o.ticker.upper() == ticker.upper()]

    def by_status(self, status: KnowledgeStatus) -> list[KnowledgeObject]:
        return [o for o in self._objects.values() if o.status == status]

    def update_content(self, object_id: str, content: dict[str, Any]):
        obj = self.get(object_id)
        if obj:
            obj.content.update(content)
            obj.version += 1
            obj.updated_at = datetime.now(UTC).isoformat()
            obj.promote(KnowledgeStatus.UPDATED)

    def count(self) -> int:
        return len(self._objects)
