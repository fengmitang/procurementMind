from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ActionResolutionStatus(StrEnum):
    EXECUTED = "EXECUTED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    ALREADY_CANCELED = "ALREADY_CANCELED"
    ALREADY_EXPIRED = "ALREADY_EXPIRED"


class ActionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_type: str = Field(default="TEST_PLATFORM", min_length=1, max_length=50)
    platform_user_id: str = Field(min_length=1, max_length=150)
    conversation_id: int = Field(gt=0)
    action_id: str = Field(min_length=16, max_length=64)
    confirmation_token: str = Field(min_length=24, max_length=128)

    @field_validator("platform_type")
    @classmethod
    def normalize_platform_type(cls, value: str) -> str:
        return value.upper()


class ActionResolutionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: str
    status: ActionResolutionStatus
    resolved_at: datetime
    result: dict[str, JsonValue] | None = None


class ResolvedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: str
    status: ActionResolutionStatus
    resolved_at: datetime
    result: dict[str, JsonValue] | None = None
