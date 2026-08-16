from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.validation import normalize_risk_signal


class Source(str, Enum):
    WEATHER = "Weather"
    PORT_CONGESTION = "Port Congestion"
    GEOPOLITICAL_RISK = "Geopolitical Risk"
    REGULATORY_COMPLIANCE = "Regulatory Compliance"


class EventIn(BaseModel):
    event_id: str = Field(min_length=1)
    source: Source
    vessel_id: str = Field(min_length=1)
    risk_signal: str
    timestamp: datetime
    confidence_score: float = Field(ge=0.0, le=1.0)

    @field_validator("risk_signal")
    @classmethod
    def _validate_risk_signal(cls, value: str) -> str:
        return normalize_risk_signal(value)
