"""Shared pydantic models for the agentic pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Transaction(BaseModel):
    id: str
    account_id: str
    amount: float
    currency: str = "EUR"
    timestamp: datetime = Field(default_factory=utcnow)
    lat: float | None = None
    lon: float | None = None
    beneficiary_id: str | None = None
    device_id: str | None = None


class ScoringContext(BaseModel):
    recent_amounts: list[float] = Field(default_factory=list)
    recent_count_last_hour: int = 0
    recent_sum_last_hour: float = 0.0
    known_beneficiaries: list[str] = Field(default_factory=list)
    known_devices: list[str] = Field(default_factory=list)
    last_location: dict[str, Any] | None = None


class RuleEngineVerdict(BaseModel):
    """Mirrors engine-rust's /v1/score response shape."""

    transaction_id: str
    risk_score: int
    risk_band: str
    triggered_rules: list[dict[str, Any]] = Field(default_factory=list)


class PreFilterVerdict(BaseModel):
    """Output of the stage-0 IsolationForest pre-filter."""

    anomaly_score: float
    is_anomaly: bool


class TriageVerdict(BaseModel):
    """Output of the stage-1 Haiku triage agent."""

    fraud_likelihood: float = Field(ge=0.0, le=1.0)
    category: str
    escalate: bool
    reasoning: str


class CaseFile(BaseModel):
    """Output of the stage-2 Sonnet investigator agent."""

    summary: str
    risk_score: int = Field(ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)
    linked_accounts: list[str] = Field(default_factory=list)
    sanctions_hit: bool = False
    recommend_compliance_review: bool


class ComplianceReport(BaseModel):
    """Output of the stage-3 Sonnet compliance agent."""

    narrative: str
    obligations_referenced: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Synthetic demonstration output only. Not legal or regulatory advice, "
        "and not a real Suspicious Activity Report."
    )


class PipelineStage(str, Enum):
    RULES = "rules"
    PREFILTER = "prefilter"
    TRIAGE = "triage"
    INVESTIGATION = "investigation"
    COMPLIANCE = "compliance"
    FUSION = "fusion"
    CLOSED = "closed"


class AgentEvent(BaseModel):
    """A single step in the pipeline's reasoning trace, streamed to the
    dashboard over WebSocket so a reviewer can see *why* a verdict was
    reached, not just the final number."""

    type: Literal["agent_event"] = "agent_event"
    transaction_id: str
    account_id: str
    stage: PipelineStage
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class Alert(BaseModel):
    type: Literal["alert"] = "alert"
    transaction_id: str
    account_id: str
    severity: Literal["low", "medium", "high", "critical"]
    title: str
    detail: dict[str, Any] = Field(default_factory=dict)
    fused_with_security_event: bool = False
    timestamp: datetime = Field(default_factory=utcnow)


class SecurityEvent(BaseModel):
    """Mirrors gateway-go's events.SecurityEvent, received over Redis."""

    type: str
    account_id: str | None = None
    severity: str
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
