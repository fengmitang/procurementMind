from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from agent_app.schemas.backend import BackendIdentity, CurrentUserData


class SkillMCPClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None): ...


SkillMCPClientFactory = Callable[
    [object, BackendIdentity, str], AbstractAsyncContextManager[SkillMCPClient]
]


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    skill_id: str
    version: str
    description: str
    supported_route: str


@dataclass(frozen=True, slots=True)
class SkillExecutionContext:
    message: str
    current_user: CurrentUserData
    identity: BackendIdentity
    trace_id: str
    purchase_request_id: int | None
    mcp_client_factory: SkillMCPClientFactory
    settings: object
    form_draft: dict[str, Any] | None = None


class DomainSkill(Protocol):
    descriptor: SkillDescriptor

    async def execute(self, context: SkillExecutionContext): ...
