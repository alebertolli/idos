from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from pathlib import Path
import json
from idos.timezone import AR_TZ

class ClaimStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"

class EvidenceCategory(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"

@dataclass
class ClaimSource:
    name: str
    url: str = ""
    date: str = ""

@dataclass
class Claim:
    claim_id: str
    statement: str
    confidence: float = 0.0
    category: EvidenceCategory = EvidenceCategory.INFERENCE
    status: ClaimStatus = ClaimStatus.ACTIVE
    sources: list[ClaimSource] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    related_claims: list[str] = field(default_factory=list)
    last_review: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(AR_TZ).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.last_review:
            self.last_review = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "confidence": self.confidence,
            "category": self.category.value,
            "status": self.status.value,
            "sources": [{"name": s.name, "url": s.url, "date": s.date} for s in self.sources],
            "tags": self.tags,
            "related_claims": self.related_claims,
            "last_review": self.last_review,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        data["category"] = EvidenceCategory(data.get("category", "INFERENCE"))
        data["status"] = ClaimStatus(data.get("status", "ACTIVE"))
        data["sources"] = [ClaimSource(**s) for s in data.get("sources", [])]
        return cls(**data)

class ClaimStore:
    def __init__(self, base_path: str | Path = "idos-knowledge"):
        self.base_path = Path(base_path)
        self._claims_dir = self.base_path / ".claims"
        self._claims_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Claim] = {}
        self._load_all()

    def _load_all(self):
        for f in self._claims_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                claim = Claim.from_dict(data)
                self._cache[claim.claim_id] = claim
            except (json.JSONDecodeError, KeyError):
                continue

    def _save(self, claim: Claim):
        path = self._claims_dir / f"{claim.claim_id}.json"
        path.write_text(json.dumps(claim.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def put(self, claim: Claim):
        claim.updated_at = datetime.now(AR_TZ).isoformat()
        self._cache[claim.claim_id] = claim
        self._save(claim)

    def get(self, claim_id: str) -> Claim | None:
        return self._cache.get(claim_id)

    def search(self, statement: str = "", tag: str = "", status: ClaimStatus | None = None) -> list[Claim]:
        results = []
        for c in self._cache.values():
            if status and c.status != status:
                continue
            if tag and tag not in c.tags:
                continue
            if statement and statement.lower() not in c.statement.lower():
                continue
            results.append(c)
        return results

    def all(self) -> list[Claim]:
        return list(self._cache.values())

    def count(self) -> int:
        return len(self._cache)

    def deprecate(self, claim_id: str, reason: str = ""):
        c = self.get(claim_id)
        if c:
            c.status = ClaimStatus.DEPRECATED
            c.tags.append(f"deprecated: {reason}" if reason else "deprecated")
            self.put(c)

    def archive(self, claim_id: str):
        c = self.get(claim_id)
        if c:
            c.status = ClaimStatus.ARCHIVED
            self.put(c)
