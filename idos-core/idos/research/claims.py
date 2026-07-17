from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class Claim:
    id: str
    statement: str
    confidence: float = 0.5
    status: str = "ACTIVE"
    sources: list[str] = field(default_factory=list)
    last_review: str = ""

    def __post_init__(self):
        if not self.last_review:
            self.last_review = datetime.now(UTC).isoformat()


class ClaimsSystem:
    def __init__(self):
        self._claims: dict[str, Claim] = {}

    def register(self, statement: str, confidence: float = 0.5,
                 sources: list[str] | None = None) -> Claim:
        claim_id = f"CLAIM-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{len(self._claims) + 1:04d}"
        claim = Claim(id=claim_id, statement=statement, confidence=confidence,
                      sources=sources or [])
        self._claims[claim_id] = claim
        return claim

    def update_confidence(self, claim_id: str, confidence: float):
        claim = self._claims.get(claim_id)
        if claim:
            claim.confidence = max(0.0, min(1.0, confidence))
            claim.last_review = datetime.now(UTC).isoformat()

    def add_source(self, claim_id: str, source: str):
        claim = self._claims.get(claim_id)
        if claim:
            if source not in claim.sources:
                claim.sources.append(source)
            claim.last_review = datetime.now(UTC).isoformat()

    def deprecate(self, claim_id: str):
        claim = self._claims.get(claim_id)
        if claim:
            claim.status = "DEPRECATED"

    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def get_active(self) -> list[Claim]:
        return [c for c in self._claims.values() if c.status == "ACTIVE"]

    def get_by_source(self, source: str) -> list[Claim]:
        return [c for c in self._claims.values() if source in c.sources]

    def all(self) -> list[Claim]:
        return list(self._claims.values())

    def count(self) -> int:
        return len(self._claims)
