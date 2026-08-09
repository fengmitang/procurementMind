from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_app.mcp.catalog import ToolFactKind, ToolNamespace


class MCPErrorCategory(StrEnum):
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    BACKEND = "backend"


class MCPResultMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: ToolNamespace
    fact_kind: ToolFactKind
    source_of_truth: str = "procurement_backend"
    visibility: str = "backend_enforced"
    authoritative: bool = True
    rag_boundary: str = "not_a_knowledge_source"


class MCPToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MCPErrorCategory
    retryable: bool
    backend_code: str | None = None


class MCPToolResponse(BaseModel):
    """Stable response envelope shared by every procurement MCP tool."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    code: str
    message: str
    data: JsonValue | None
    source: str
    trace_id: str
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    metadata: MCPResultMetadata | None = None
    error: MCPToolError | None = None

    @classmethod
    def ok(
        cls,
        data: Any,
        *,
        source: str,
        trace_id: str,
        metadata: MCPResultMetadata | None = None,
    ) -> "MCPToolResponse":
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        return cls(
            success=True,
            code="OK",
            message="success",
            data=data,
            source=source,
            trace_id=trace_id,
            metadata=metadata,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        source: str,
        trace_id: str,
        metadata: MCPResultMetadata | None = None,
        error: MCPToolError | None = None,
    ) -> "MCPToolResponse":
        return cls(
            success=False,
            code=code,
            message=message,
            data=None,
            source=source,
            trace_id=trace_id,
            warnings=[message],
            metadata=metadata,
            error=error,
        )
