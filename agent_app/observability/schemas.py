from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_app.graph.schemas import GraphError, ToolExecution, TraceEvent


class ModelUsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    provider: str | None = None
    model: str | None = None
    call_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: str | None = None
    currency: str | None = None


class ExecutionComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["GRAPH", "MCP", "MODEL", "RAG", "REVIEW"]
    status: Literal[
        "SUCCESS",
        "PARTIAL",
        "FAILED",
        "SKIPPED",
        "NOT_CONFIGURED",
    ]
    detail: str


class ExecutionDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    route: str
    status: Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_AVAILABLE"]
    duration_ms: int = Field(ge=0)
    step_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    restored_from_snapshot: bool
    components: list[ExecutionComponent]
    model_usage: ModelUsageSummary
    trace_events: list[TraceEvent]
    tools: list[ToolExecution]
    plan: dict[str, JsonValue] | None = None
    review: dict[str, JsonValue] | None = None
    errors: list[GraphError]
