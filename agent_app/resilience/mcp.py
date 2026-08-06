from typing import Any, Protocol

from agent_app.mcp.client import MCPClientError
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError


class MCPToolCaller(Protocol):
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResponse: ...


class CircuitProtectedMCPClient:
    def __init__(
        self,
        client: MCPToolCaller,
        circuit_breaker: AsyncCircuitBreaker,
    ) -> None:
        self.client = client
        self.circuit_breaker = circuit_breaker

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResponse:
        async def invoke() -> MCPToolResponse:
            return await self.client.call_tool(name, arguments)

        try:
            return await self.circuit_breaker.call(invoke)
        except CircuitOpenError as exc:
            raise MCPClientError(
                "MCP_CIRCUIT_OPEN",
                f"MCP 工具服务熔断中，约 {max(1, round(exc.retry_after_seconds))} 秒后重试",
            ) from exc
