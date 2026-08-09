from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ModelPurpose(StrEnum):
    ROUTER = "ROUTER"
    QUERY_REWRITE = "QUERY_REWRITE"
    ANALYSIS_PLAN = "ANALYSIS_PLAN"
    ANALYSIS_REPLAN = "ANALYSIS_REPLAN"
    COMPOSE = "COMPOSE"
    REVIEW = "REVIEW"


class ModelUsageSource(StrEnum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    UNAVAILABLE = "UNAVAILABLE"


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
    source: ModelUsageSource = ModelUsageSource.UNAVAILABLE

    @model_validator(mode="after")
    def reject_estimated_or_incomplete_usage(self) -> "ModelUsage":
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        populated = [value is not None for value in values]
        if any(populated) and not all(populated):
            raise ValueError("模型 Token 用量必须完整提供 input/output/total")
        if all(populated):
            if self.source is not ModelUsageSource.PROVIDER_REPORTED:
                raise ValueError("Token 用量只能标记为供应商真实返回")
            assert self.input_tokens is not None
            assert self.output_tokens is not None
            assert self.total_tokens is not None
            if self.total_tokens < self.input_tokens + self.output_tokens:
                raise ValueError("total_tokens 不能小于 input_tokens + output_tokens")
        elif self.source is not ModelUsageSource.UNAVAILABLE:
            raise ValueError("未提供 Token 用量时 source 必须为 UNAVAILABLE")
        return self


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
