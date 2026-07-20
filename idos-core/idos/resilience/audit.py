from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import hashlib
import json
from idos.timezone import AR_TZ

@dataclass
class AuditEntry:
    action: str
    entity_type: str
    entity_id: str
    actor: str
    details: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = ""
    hash: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(AR_TZ).isoformat()
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = f"{self.timestamp}|{self.action}|{self.entity_type}|{self.entity_id}|{self.actor}|{json.dumps(self.details, sort_keys=True)}|{self.previous_hash}"
        return hashlib.sha256(content.encode()).hexdigest()

class AuditTrail:
    def __init__(self):
        self._entries: list[AuditEntry] = []

    def record(self, action: str, entity_type: str, entity_id: str,
               actor: str, details: dict[str, Any] | None = None):
        previous_hash = self._entries[-1].hash if self._entries else ""
        entry = AuditEntry(
            action=action, entity_type=entity_type, entity_id=entity_id,
            actor=actor, details=details or {},
            previous_hash=previous_hash,
        )
        self._entries.append(entry)
        return entry

    def get_by_entity(self, entity_type: str, entity_id: str) -> list[AuditEntry]:
        return [
            e for e in self._entries
            if e.entity_type == entity_type and e.entity_id == entity_id
        ]

    def get_by_actor(self, actor: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.actor == actor]

    def get_by_action(self, action: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.action == action]

    def verify_chain(self) -> bool:
        for i, entry in enumerate(self._entries):
            expected_hash = entry._compute_hash()
            if entry.hash != expected_hash:
                return False
            if i > 0 and entry.previous_hash != self._entries[i - 1].hash:
                return False
        return True

    def recent(self, n: int = 10) -> list[AuditEntry]:
        return self._entries[-n:]

    def all(self) -> list[AuditEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()
