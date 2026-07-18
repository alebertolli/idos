from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class ContradictionSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class Contradiction:
    id: str = ""
    ticker: str = ""
    claim_id: str = ""
    claim_statement: str = ""
    conflicting_evidence: str = ""
    source: str = ""
    severity: ContradictionSeverity = ContradictionSeverity.MEDIUM
    resolved: bool = False
    resolution: str = ""
    created_at: str = ""
    resolved_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "claim_id": self.claim_id,
            "claim_statement": self.claim_statement,
            "conflicting_evidence": self.conflicting_evidence,
            "source": self.source,
            "severity": self.severity.value,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ContradictionDetector:
    def __init__(self):
        self._contradictions: list[Contradiction] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"CON-{datetime.now(UTC).strftime('%Y%m%d')}-{self._counter:04d}"

    def evaluate(self, ticker: str, claim_statement: str,
                 new_evidence: str, source: str = "") -> Contradiction | None:
        import re
        def singularize(word: str) -> str:
            return re.sub(r"(?<=[a-z])s$", "", word)
        claim_lower = claim_statement.lower()
        evidence_lower = new_evidence.lower()
        keywords_claim = {singularize(w) for w in re.findall(r"\b[a-z]+\b", claim_lower)}
        keywords_evidence = {singularize(w) for w in re.findall(r"\b[a-z]+\b", evidence_lower)}
        overlap = keywords_claim & keywords_evidence

        negation_words = {"no", "not", "never", "decline", "declined", "declining",
                          "drop", "dropped", "reduce", "reduced", "decrease", "fell",
                          "fall", "falling", "negative", "weak", "weaker", "worst",
                          "down", "loss", "lost", "shrink", "shrinking"}
        positive_words = {"growth", "growing", "increase", "increased", "increasing",
                          "expand", "expanding", "expansion", "strong", "stronger",
                          "improve", "improved", "improving", "record", "positive",
                          "best", "lead", "dominant", "dominance", "up", "gain",
                          "gains", "profit", "profitable", "rising", "rise"}

        claim_has_negation = bool(keywords_claim & negation_words)
        claim_has_positive = bool(keywords_claim & positive_words)
        evidence_has_negation = bool(keywords_evidence & negation_words)
        evidence_has_positive = bool(keywords_evidence & positive_words)

        contradicts = False
        severity = ContradictionSeverity.LOW

        if overlap:
            topic_overlap = len(overlap) >= 1
            if topic_overlap:
                if claim_has_positive and evidence_has_negation:
                    contradicts = True
                    severity = ContradictionSeverity.HIGH
                elif claim_has_negation and evidence_has_positive:
                    contradicts = True
                    severity = ContradictionSeverity.HIGH
                elif len(overlap) >= 4:
                    contradicts = True
                    severity = ContradictionSeverity.MEDIUM
                elif len(overlap) >= 2 and (claim_has_positive or evidence_has_positive):
                    contradicts = True
                    severity = ContradictionSeverity.LOW

        if not contradicts:
            return None

        c = Contradiction(
            id=self._next_id(),
            ticker=ticker.upper(),
            claim_statement=claim_statement,
            conflicting_evidence=new_evidence,
            source=source,
            severity=severity,
        )
        self._contradictions.append(c)
        return c

    def resolve(self, contradiction_id: str, resolution: str):
        for c in self._contradictions:
            if c.id == contradiction_id:
                c.resolved = True
                c.resolution = resolution
                c.resolved_at = datetime.now(UTC).isoformat()
                return True
        return False

    def unresolved(self) -> list[Contradiction]:
        return [c for c in self._contradictions if not c.resolved]

    def by_ticker(self, ticker: str) -> list[Contradiction]:
        return [c for c in self._contradictions if c.ticker.upper() == ticker.upper()]

    def all(self) -> list[Contradiction]:
        return list(self._contradictions)
