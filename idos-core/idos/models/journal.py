from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from idos.models.enums import (
    OpportunityStatus,
    AssessmentStatus,
    DecisionType,
    ReviewType,
)
from idos.models.conviction import Conviction
from idos.timezone import AR_TZ

class CaseFile(BaseModel):
    ticker: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    opportunity_ids: list[str] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)

class Opportunity(BaseModel):
    id: str
    ticker: str
    status: OpportunityStatus = OpportunityStatus.DISCOVERED
    created_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    conviction: Conviction = Field(default_factory=Conviction)
    hypothesis_ids: list[str] = Field(default_factory=list)
    assessment_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    review_ids: list[str] = Field(default_factory=list)

class Assessment(BaseModel):
    id: str
    engine: str
    version: str = "1.0"
    status: AssessmentStatus = AssessmentStatus.PENDING
    score: int = Field(default=0, ge=0, le=100)
    confidence: str = "MEDIUM"
    findings: list[dict] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)
    recommendation: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))

class Decision(BaseModel):
    id: str
    type: DecisionType
    opportunity_id: str
    justification: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    evidence_ids: list[str] = Field(default_factory=list)
    assessment_ids: list[str] = Field(default_factory=list)
    rules_applied: list[str] = Field(default_factory=list)
    author: str = "system"

class PortfolioPosition(BaseModel):
    ticker: str
    opportunity_id: str
    avg_entry_price: float = 0.0
    shares: int = 0
    weight_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    stop_loss: float = 0.0
    status: str = "ACTIVE"
    conviction: Conviction = Field(default_factory=Conviction)

class Review(BaseModel):
    id: str
    type: ReviewType
    opportunity_id: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    author: str = "system"

class ProvenanceEntry(BaseModel):
    id: str
    target_id: str
    target_field: str
    source: str
    evidence_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
