from typing import Any

from pydantic import BaseModel, Field


class DemoProxyRequest(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=150)
    method: str
    path: str = Field(min_length=1, max_length=500)
    query: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
