from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ModelPurpose(StrEnum):
    ANALYSIS_PLAN = "ANALYSIS_PLAN"
    ANALYSIS_REPLAN = "ANALYSIS_REPLAN"
    REVIEW = "REVIEW"


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=50000)


class StructuredModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: ModelPurpose
    trace_id: str = Field(min_length=1, max_length=128)
    messages: list[ModelMessage] = Field(min_length=1, max_length=20)
    response_schema: dict[str, JsonValue]
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=2000, ge=1, le=32000)


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class StructuredModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    output: dict[str, JsonValue]
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: int = Field(ge=0)
    request_id: str | None = None


class ModelAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class StructuredModelAdapter(Protocol):
    async def complete_structured(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse: ...
