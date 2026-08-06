from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue


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

    @classmethod
    def ok(cls, data: Any, *, source: str, trace_id: str) -> "MCPToolResponse":
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        return cls(
            success=True,
            code="OK",
            message="success",
            data=data,
            source=source,
            trace_id=trace_id,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        source: str,
        trace_id: str,
    ) -> "MCPToolResponse":
        return cls(
            success=False,
            code=code,
            message=message,
            data=None,
            source=source,
            trace_id=trace_id,
            warnings=[message],
        )
