from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_app.analysis.schemas import AnalysisOutput
from agent_app.investigation.schemas import RiskInvestigationOutput
from agent_app.observability.schemas import ExecutionDetails


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_type: str = Field(default="TEST_PLATFORM", min_length=1, max_length=50)
    platform_user_id: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=8000)
    external_conversation_id: str | None = Field(default=None, max_length=150)
    external_message_id: str | None = Field(default=None, max_length=150)

    @field_validator("platform_type")
    @classmethod
    def normalize_platform_type(cls, value: str) -> str:
        return value.upper()


class ChatData(BaseModel):
    task_id: UUID
    conversation_id: int
    status: Literal["ACCEPTED"] = "ACCEPTED"
    reply: str
    route: str
    restored_from_snapshot: bool
    tool_call_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    execution: ExecutionDetails
    analysis: AnalysisOutput | None = None
    risk_investigation: RiskInvestigationOutput | None = None
