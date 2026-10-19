from datetime import datetime
from typing import Any
from idos.models.knowledge import Evidence
from idos.models.enums import EvidenceType, ConfidenceLevel
from idos.timezone import AR_TZ

class EvidenceChainManager:
    def __init__(self):
        self._chain: dict[str, Evidence] = {}
        self._links: dict[str, list[str]] = {}

    def add_evidence(self, description: str, source: str, event_date: str,
                     type: EvidenceType = EvidenceType.OTHER,
                     reliability: ConfidenceLevel = ConfidenceLevel.MEDIUM) -> Evidence:
        ev_id = f"EVI-{datetime.now(AR_TZ).strftime('%Y%m%d%H%M%S')}-{len(self._chain) + 1:04d}"
        evidence = Evidence(
            id=ev_id, description=description, type=type,
            source=source, event_date=event_date, reliability=reliability,
        )
        self._chain[ev_id] = evidence
        return evidence

    def link(self, target_id: str, evidence_id: str):
        if evidence_id not in self._chain:
            raise ValueError(f"Evidence {evidence_id} not found")
        if target_id not in self._links:
            self._links[target_id] = []
        self._links[target_id].append(evidence_id)

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self._chain.get(evidence_id)

    def get_chain(self, target_id: str) -> list[Evidence]:
        return [self._chain[eid] for eid in self._links.get(target_id, []) if eid in self._chain]

    def get_all_evidence(self) -> list[Evidence]:
        return list(self._chain.values())

    def count(self) -> int:
        return len(self._chain)

    def clear(self):
        self._chain.clear()
        self._links.clear()
