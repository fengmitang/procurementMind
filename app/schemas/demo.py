from typing import Any

from pydantic import BaseModel, Field


class DemoProxyRequest(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=150)
    method: str
    path: str = Field(min_length=1, max_length=500)
    query: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None


class DemoAgentChatRequest(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=8000)
    external_conversation_id: str | None = Field(default=None, max_length=150)
    external_message_id: str | None = Field(default=None, max_length=150)
    ui_context: dict[str, Any] | None = None


class DemoAgentActionRequest(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=150)
    conversation_id: int = Field(gt=0)
    action_id: str = Field(min_length=16, max_length=64)
    confirmation_token: str = Field(min_length=24, max_length=128)
