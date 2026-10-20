from pydantic import BaseModel, Field
from idos.models.enums import ConfidenceLevel, ConvictionTrend


class Conviction(BaseModel):
    overall: int = Field(default=0, ge=0, le=100)
    scores: dict[str, int] = Field(default_factory=lambda: {
        "business": 0,
        "valuation": 0,
        "rerating": 0,
        "risk": 0,
        "portfolio_fit": 0,
    })
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    trend: ConvictionTrend = ConvictionTrend.STABLE
