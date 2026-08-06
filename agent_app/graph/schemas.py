from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_app.analysis.schemas import AnalysisOutput
from agent_app.investigation.schemas import RiskInvestigationOutput
from agent_app.schemas.backend import (
    BackendIdentity,
    ConversationStateData,
    CurrentUserData,
)


class RouteType(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    REALTIME_BUSINESS = "REALTIME_BUSINESS"
    HYBRID = "HYBRID"
    COMPLEX_QUERY = "COMPLEX_QUERY"
    RISK_INVESTIGATION = "RISK_INVESTIGATION"


class TraceEventType(StrEnum):
    ROUTE = "ROUTE"
    TOOL = "TOOL"
    GRAPH = "GRAPH"
    ERROR = "ERROR"


class GraphError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    recoverable: bool = True
    source: str | None = None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    source: str
    reference_id: str | None = None
    data: JsonValue


class ToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    success: bool
    code: str
    source: str
    trace_id: str
    duration_ms: int = Field(ge=0)
    data: JsonValue | None = None


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: TraceEventType
    name: str
    status: str
    duration_ms: int = Field(default=0, ge=0)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    result: JsonValue | None = None
    error_code: str | None = None


class GraphRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    trace_id: str = Field(min_length=1, max_length=128)
    conversation_id: int = Field(gt=0)
    identity: BackendIdentity
    current_user: CurrentUserData
    message: str = Field(min_length=1, max_length=8000)
    restored_state: ConversationStateData | None = None


class GraphRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    trace_id: str
    conversation_id: int
    route: RouteType
    reply: str
    purchase_request_id: int | None
    restored_from_snapshot: bool
    duration_ms: int = Field(ge=0)
    step_count: int
    tool_call_count: int
    evidence: list[Evidence]
    tool_results: list[ToolExecution]
    errors: list[GraphError]
    trace_events: list[TraceEvent]
    analysis: AnalysisOutput | None = None
    risk_investigation: RiskInvestigationOutput | None = None


class GraphState(TypedDict, total=False):
    task_id: str
    trace_id: str
    conversation_id: int
    identity: dict[str, JsonValue]
    current_user: dict[str, JsonValue]
    message: str
    route: str
    purchase_request_id: int | None
    restored_from_snapshot: bool
    step_count: int
    tool_call_count: int
    evidence: list[dict[str, JsonValue]]
    tool_results: list[dict[str, JsonValue]]
    errors: list[dict[str, JsonValue]]
    trace_events: list[dict[str, JsonValue]]
    reply: str
    analysis_query_context: dict[str, JsonValue] | None
    analysis: dict[str, JsonValue] | None
    risk_investigation: dict[str, JsonValue] | None
