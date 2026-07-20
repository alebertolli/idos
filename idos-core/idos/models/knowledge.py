from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from idos.models.enums import HypothesisStatus, EvidenceType, ConfidenceLevel
from idos.timezone import AR_TZ

class Company(BaseModel):
    ticker: str
    isin: Optional[str] = None
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    exchange: Optional[str] = None
    currency: str = "USD"
    competitors: list[str] = Field(default_factory=list)
    ipo_date: Optional[str] = None

class StaticKnowledge(BaseModel):
    business_model: Optional[str] = None
    products: list[str] = Field(default_factory=list)
    moat_description: Optional[str] = None
    competitive_advantages: list[str] = Field(default_factory=list)
    management_history: Optional[str] = None
    founder_info: Optional[str] = None

class DynamicKnowledge(BaseModel):
    last_updated: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    financials: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    price_history: list[dict] = Field(default_factory=list)

class GeneratedKnowledge(BaseModel):
    aoif_analysis: list[dict] = Field(default_factory=list)
    summaries: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)

class KnowledgeBase(BaseModel):
    ticker: str
    static: StaticKnowledge = Field(default_factory=StaticKnowledge)
    dynamic: DynamicKnowledge = Field(default_factory=DynamicKnowledge)
    generated: GeneratedKnowledge = Field(default_factory=GeneratedKnowledge)

class Prediction(BaseModel):
    id: str
    variable: str
    expected_value: float
    tolerance_pct: float = 5.0
    measurement_date: str
    observed_value: Optional[float] = None
    status: str = "PENDING"

class Hypothesis(BaseModel):
    id: str
    opportunity_id: str
    ticker: str
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(AR_TZ))
    horizon: str = "36 months"
    author: str = "system"
    status: HypothesisStatus = HypothesisStatus.DRAFT
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    statement: str = ""
    falsification_conditions: list[str] = Field(default_factory=list)
    secondary_hypotheses: list[str] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)

class Evidence(BaseModel):
    id: str
    description: str
    type: EvidenceType = EvidenceType.OTHER
    source: str
    event_date: str
    reliability: ConfidenceLevel = ConfidenceLevel.MEDIUM
    impact: Optional[str] = None

class Rule(BaseModel):
    id: str
    description: str
    priority: int = 0
    condition: str
    action: str
    version: str = "1.0"
    active: bool = True
