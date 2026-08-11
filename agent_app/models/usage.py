from pydantic import BaseModel, ConfigDict, Field

from agent_app.models.protocols import ModelPurpose, StructuredModelResponse


class ModelCallUsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: ModelPurpose
    provider: str
    model: str
    primary_model: str
    actual_model: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    attempts: int = Field(ge=1)
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    provider_reported: bool
    request_id: str | None = None


class ModelUsageLedgerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool


class ModelUsageLedger:
    """Collect provider-reported usage without estimating missing values."""

    def __init__(self) -> None:
        self.records: list[ModelCallUsageRecord] = []

    def record(
        self,
        purpose: ModelPurpose,
        response: StructuredModelResponse,
        attempts: int,
    ) -> None:
        usage = response.usage
        provider_reported = usage.total_tokens is not None
        self.records.append(
            ModelCallUsageRecord(
                purpose=purpose,
                provider=response.provider,
                model=response.model,
                primary_model=response.primary_model or response.model,
                actual_model=response.actual_model or response.model,
                fallback_used=response.fallback_used,
                fallback_reason=response.fallback_reason,
                attempts=attempts,
                latency_ms=response.latency_ms,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                provider_reported=provider_reported,
                request_id=response.request_id,
            )
        )

    def summary(self) -> ModelUsageLedgerSummary:
        complete = bool(self.records) and all(item.provider_reported for item in self.records)
        return ModelUsageLedgerSummary(
            call_count=len(self.records),
            input_tokens=(
                sum(item.input_tokens or 0 for item in self.records) if complete else None
            ),
            output_tokens=(
                sum(item.output_tokens or 0 for item in self.records) if complete else None
            ),
            total_tokens=(
                sum(item.total_tokens or 0 for item in self.records) if complete else None
            ),
            usage_complete=complete,
        )
