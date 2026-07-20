from datetime import datetime, UTC
from typing import Any
from uuid import uuid4
from idos.data.sqlite import SQLiteStore
from idos.models.journal import ProvenanceEntry


class ProvenanceEngine:
    def __init__(self, store: SQLiteStore):
        self._store = store

    def link(self, target_id: str, target_field: str, source: str, evidence_id: str) -> ProvenanceEntry:
        entry = ProvenanceEntry(
            id=f"PROV-{uuid4().hex[:12]}",
            target_id=target_id,
            target_field=target_field,
            source=source,
            evidence_id=evidence_id,
            timestamp=datetime.now(UTC),
        )
        c = self._store.conn
        c.execute(
            "INSERT INTO provenance_chain (target_id, target_field, source, evidence_id, timestamp) VALUES (?, ?, ?, ?, ?)",
            (entry.target_id, entry.target_field, entry.source, entry.evidence_id, entry.timestamp.isoformat()),
        )
        c.commit()
        return entry

    def get_chain(self, target_id: str) -> list[dict[str, Any]]:
        c = self._store.conn
        rows = c.execute(
            "SELECT target_id, target_field, source, evidence_id, timestamp FROM provenance_chain WHERE target_id = ? ORDER BY timestamp",
            (target_id,),
        )
        return [dict(r) for r in rows.fetchall()]

    def get_by_evidence(self, evidence_id: str) -> list[dict[str, Any]]:
        c = self._store.conn
        rows = c.execute(
            "SELECT target_id, target_field, source, evidence_id, timestamp FROM provenance_chain WHERE evidence_id = ? ORDER BY timestamp",
            (evidence_id,),
        )
        return [dict(r) for r in rows.fetchall()]

    def count(self) -> int:
        c = self._store.conn
        row = c.execute("SELECT COUNT(*) FROM provenance_chain").fetchone()
        return row[0] if row else 0

    def clear(self):
        c = self._store.conn
        c.execute("DELETE FROM provenance_chain")
        c.commit()
