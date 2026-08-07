from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, AliasChoices
from typing import Any, Optional
from idos.models.enums import HypothesisStatus, HypothesisPriority, EvidenceCategory, EvidenceType, ConfidenceLevel
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
    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    metric: str = Field(default="", validation_alias=AliasChoices("metric", "variable"))
    expected_value: float = 0.0
    tolerance_pct: float = 5.0
    unit: str = "%"
    deadline: str = Field(default="", validation_alias=AliasChoices("deadline", "measurement_date"))
    actual_value: Optional[float] = Field(default=None, validation_alias=AliasChoices("actual_value", "observed_value"))
    met: Optional[bool] = None
    status: str = "PENDING"
    notes: str = ""

    def evaluate(self) -> Optional[bool]:
        if self.actual_value is None:
            return None
        self.met = self.actual_value >= self.expected_value
        self.status = "MET" if self.met else "FAILED"
        return self.met


class FalsificationCondition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    condition: str = ""
    metric: str = ""
    threshold: float = 0.0
    triggered: bool = False
    triggered_at: str = ""


class EvidenceLink(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    claim: str = ""
    category: EvidenceCategory = EvidenceCategory.FACT
    source: str = ""
    date: str = ""


class Hypothesis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    opportunity_id: str
    ticker: str
    statement: str = ""
    status: HypothesisStatus = HypothesisStatus.DRAFT
    priority: HypothesisPriority = HypothesisPriority.IMPORTANT
    version: int = 1
    horizon: str = "24 months"
    author: str = "system"
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parent_id: str = ""
    falsification: list[FalsificationCondition] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    secondary_hypotheses: list[str] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    evidence: list[EvidenceLink] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __init__(self, **data: Any):
        super().__init__(**data)
        now = datetime.now(AR_TZ).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        for fc in self.falsification:
            self.falsification_conditions.append(fc.condition)

    def promote(self, target: HypothesisStatus):
        order = list(HypothesisStatus)
        current_idx = order.index(self.status)
        target_idx = order.index(target)
        if target_idx >= current_idx:
            self.status = target
            self.updated_at = datetime.now(AR_TZ).isoformat()

    def check_falsification(self) -> list[str]:
        triggered = []
        for fc in self.falsification:
            if fc.triggered:
                triggered.append(fc.condition)
        if triggered:
            self.status = HypothesisStatus.INVALIDATED
            self.updated_at = datetime.now(AR_TZ).isoformat()
        return triggered

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "ticker": self.ticker,
            "statement": self.statement,
            "status": self.status.value,
            "priority": self.priority.value,
            "version": self.version,
            "probability": self.probability,
            "confidence": self.confidence,
            "falsification_conditions": self.falsification_conditions,
            "predictions": [{"metric": p.metric, "expected": p.expected_value,
                             "unit": p.unit, "deadline": p.deadline,
                             "actual": p.actual_value, "met": p.met} for p in self.predictions],
            "falsification": [{"condition": f.condition, "metric": f.metric,
                               "threshold": f.threshold, "triggered": f.triggered}
                              for f in self.falsification],
        }


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
