from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_app.analysis.schemas import AnalysisOutput
from agent_app.graph.schemas import PendingAction, UIContext
from agent_app.investigation.schemas import RiskInvestigationOutput
from agent_app.models.role_schemas import ReviewOutput
from agent_app.observability.schemas import ExecutionDetails
from agent_app.rag.schemas import RetrievalResult


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_type: str = Field(default="TEST_PLATFORM", min_length=1, max_length=50)
    platform_user_id: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=8000)
    external_conversation_id: str | None = Field(default=None, max_length=150)
    external_message_id: str | None = Field(default=None, max_length=150)
    ui_context: UIContext | None = None

    @field_validator("platform_type")
    @classmethod
    def normalize_platform_type(cls, value: str) -> str:
        return value.upper()


class KnowledgeSourceData(BaseModel):
    title: str
    section_path: list[str] = Field(default_factory=list)


class BusinessResultData(BaseModel):
    kind: Literal["PURCHASE_REQUIREMENTS", "SUPPLIERS", "PURCHASE_HISTORY"]
    title: str
    items: list[dict] = Field(default_factory=list)
    total: int | None = None


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
    knowledge: RetrievalResult | None = None
    knowledge_sources: list[KnowledgeSourceData] = Field(default_factory=list)
    business_results: list[BusinessResultData] = Field(default_factory=list)
    form_draft: dict | None = None
    form_missing_fields: list[str] = Field(default_factory=list)
    review: ReviewOutput | None = None
    evidence_sufficient: bool = False
    pending_action: PendingAction | None = None
    performance: dict[str, int] = Field(default_factory=dict)
