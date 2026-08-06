import os
from dataclasses import dataclass

from pydantic import ValidationError

from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.config import AgentSettings
from agent_app.schemas.backend import BackendIdentity

PLATFORM_TYPE_ENV = "PROCUREMENT_MCP_PLATFORM_TYPE"
PLATFORM_USER_ID_ENV = "PROCUREMENT_MCP_PLATFORM_USER_ID"
TRACE_ID_ENV = "PROCUREMENT_MCP_TRACE_ID"


class MCPTrustedContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPTrustedContext:
    identity: BackendIdentity
    trace_id: str

    @classmethod
    def from_environment(cls) -> "MCPTrustedContext":
        trace_id = os.environ.get(TRACE_ID_ENV, "").strip()
        try:
            identity = BackendIdentity(
                platform_type=os.environ.get(PLATFORM_TYPE_ENV, ""),
                platform_user_id=os.environ.get(PLATFORM_USER_ID_ENV, ""),
            )
        except ValidationError as exc:
            raise MCPTrustedContextError("MCP 可信用户身份缺失或无效") from exc
        if not trace_id or len(trace_id) > 128:
            raise MCPTrustedContextError("MCP Trace ID 缺失或无效")
        return cls(identity=identity, trace_id=trace_id)


@dataclass
class MCPRuntime:
    settings: AgentSettings
    context: MCPTrustedContext
    backend: ProcurementBackendClient

    @classmethod
    def from_environment(cls) -> "MCPRuntime":
        settings = AgentSettings()
        return cls(
            settings=settings,
            context=MCPTrustedContext.from_environment(),
            backend=ProcurementBackendClient(settings),
        )

    async def aclose(self) -> None:
        await self.backend.aclose()
