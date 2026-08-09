from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class InvestigationEvidenceKind(StrEnum):
    REQUIREMENT = "REQUIREMENT"
    RISK_SIGNALS = "RISK_SIGNALS"
    HISTORICAL_PRICE = "HISTORICAL_PRICE"
    SUPPLIER_PERFORMANCE = "SUPPLIER_PERFORMANCE"
    SIMILAR_CASES = "SIMILAR_CASES"
    KNOWLEDGE_RULE = "KNOWLEDGE_RULE"


class EvidenceStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class InvestigationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: InvestigationEvidenceKind
    status: EvidenceStatus
    source: str
    tool_name: str | None = None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    data: JsonValue | None = None
    code: str | None = None
    message: str | None = None
    trace_id: str | None = None
    duration_ms: int = Field(default=0, ge=0)


class RiskSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_code: str
    risk_type: str
    risk_level: str
    backend_rule_matched: bool
    facts: dict[str, JsonValue]
    metrics: dict[str, JsonValue]
    related_record_ids: list[int]
    data_sources: list[str]
    applicable_rule: dict[str, JsonValue]
    possible_causes: list[str]
    information_complete: bool
    information_gaps: list[str]
    human_checks: list[str]


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    risk_code: str | None = None
    message: str


class ProgramReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    checked_items: int = Field(ge=0)
    findings: list[ReviewFinding] = Field(default_factory=list)


class RiskInvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: int
    answer: str
    summary_items: list[RiskSummaryItem]
    evidence: list[InvestigationEvidence]
    review: ProgramReviewResult
    complete: bool
    knowledge_evidence_available: bool = False
    warnings: list[str] = Field(default_factory=list)
