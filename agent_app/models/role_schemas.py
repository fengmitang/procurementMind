from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRoute(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    REALTIME_BUSINESS = "REALTIME_BUSINESS"
    HYBRID = "HYBRID"
    COMPLEX_QUERY = "COMPLEX_QUERY"
    RISK_INVESTIGATION = "RISK_INVESTIGATION"
    FORM_PREFILL = "FORM_PREFILL"


class RouterOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: ModelRoute
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    requires_realtime_tools: bool
    requires_knowledge: bool

    @model_validator(mode="after")
    def route_must_match_required_capabilities(self) -> "RouterOutput":
        expected = {
            ModelRoute.KNOWLEDGE: (False, True),
            ModelRoute.REALTIME_BUSINESS: (True, False),
            ModelRoute.HYBRID: (True, True),
            ModelRoute.COMPLEX_QUERY: (True, False),
            ModelRoute.RISK_INVESTIGATION: (True, True),
            ModelRoute.FORM_PREFILL: (False, False),
        }[self.route]
        if (self.requires_realtime_tools, self.requires_knowledge) != expected:
            raise ValueError("路由和所需能力标记不一致")
        return self


class QueryRewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewritten_query: str = Field(min_length=1, max_length=2000)
    changed: bool
    preserved_entities: list[str] = Field(default_factory=list, max_length=20)


class ComposeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^K[1-9][0-9]*$")
    claim: str = Field(min_length=1, max_length=1000)


class ComposeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=12000)
    citations: list[ComposeCitation] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    requires_human_confirmation: bool = False


class ReviewIssueCode(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    OMITTED_CONSTRAINT = "OMITTED_CONSTRAINT"
    ANALYSIS_AS_FACT = "ANALYSIS_AS_FACT"
    AUTHORITY_EXCEEDED = "AUTHORITY_EXCEEDED"
    INVISIBLE_EVIDENCE = "INVISIBLE_EVIDENCE"
    RAG_TOOL_CONFLICT = "RAG_TOOL_CONFLICT"
    HUMAN_CONFIRMATION_REQUIRED = "HUMAN_CONFIRMATION_REQUIRED"


class ReviewSeverity(StrEnum):
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ReviewIssueCode
    severity: ReviewSeverity
    message: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=20)
    requires_human_confirmation: bool
    revised_answer: str | None = Field(default=None, max_length=12000)

    @model_validator(mode="after")
    def passed_cannot_include_blocking_issues(self) -> "ReviewOutput":
        has_blocking = any(issue.severity is ReviewSeverity.BLOCKING for issue in self.issues)
        if self.passed and has_blocking:
            raise ValueError("Review 通过时不能包含阻断问题")
        if not self.passed and not has_blocking:
            raise ValueError("Review 不通过时必须包含至少一个阻断问题")
        return self
