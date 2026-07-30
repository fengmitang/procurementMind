from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ActiveConversationRequest(BaseModel):
    current_action: str = Field(min_length=1, max_length=30)
    external_conversation_id: str | None = Field(default=None, max_length=150)


class ActiveConversationData(BaseModel):
    conversation_id: int
    status: str
    purchase_request_id: int | None
    redis_state_exists: bool


class CreateMessageRequest(BaseModel):
    external_message_id: str | None = Field(default=None, max_length=150)
    sender_type: str
    content: str = Field(min_length=1)

    @field_validator("sender_type")
    @classmethod
    def validate_sender_type(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"USER", "AGENT", "SYSTEM"}:
            raise ValueError("sender_type 必须是 USER、AGENT 或 SYSTEM")
        return normalized


class MessageData(BaseModel):
    message_id: int
    external_message_id: str | None
    sender_type: str
    content: str
    created_at: datetime


class MessageCreatedData(BaseModel):
    message_id: int
    created_at: datetime
    duplicate: bool = False


class MessageListData(BaseModel):
    items: list[MessageData]
    page: int
    page_size: int
    total: int


class ConversationStatePayload(BaseModel):
    purchase_request_id: int | None = None
    current_action: str = Field(min_length=1, max_length=30)
    collected_data: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    awaiting_confirmation: bool = False
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    last_recommendations: list[dict[str, Any]] = Field(default_factory=list)


class ConversationStateData(ConversationStatePayload):
    conversation_id: int
    restored_from_snapshot: bool = False


class StateSavedData(BaseModel):
    saved: bool = True
    expires_in_seconds: int


class SaveSnapshotRequest(BaseModel):
    snapshot_reason: str = Field(min_length=1, max_length=50)


class SnapshotSavedData(BaseModel):
    state_id: int
    saved_at: datetime


class CompleteConversationRequest(BaseModel):
    purchase_request_id: int | None = None


class ConversationCompletedData(BaseModel):
    conversation_id: int
    status: str
    redis_state_deleted: bool
