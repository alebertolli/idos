from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class AssessmentResult:
    engine: str
    version: str = "1.0"
    score: int = 0
    confidence: str = "MEDIUM"
    findings: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    recommendation: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()

    def to_assessment_dict(self, opp_id: str) -> dict[str, Any]:
        return {
            "id": f"{self.engine}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "engine": self.engine,
            "version": self.version,
            "status": "COMPLETED",
            "score": self.score,
            "confidence": self.confidence,
            "findings": self.findings,
            "risks": self.risks,
            "recommendation": self.recommendation,
            "evidence_ids": self.evidence_ids,
            "dependencies": self.dependencies,
            "generated_at": self.generated_at,
        }


class BaseAssessmentEngine:
    name: str = "base"
    version: str = "1.0"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        raise NotImplementedError
