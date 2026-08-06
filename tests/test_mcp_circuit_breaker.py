import pytest

from agent_app.mcp.client import MCPClientError
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.resilience import AsyncCircuitBreaker
from agent_app.resilience.mcp import CircuitProtectedMCPClient


class FailingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls += 1
        raise MCPClientError("MCP_TRANSPORT_ERROR", "连接断开")


class BusinessFailureClient:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls += 1
        return MCPToolResponse.failure(
            "PERMISSION_DENIED",
            "无权访问",
            source="/api/v1/requirements/1",
            trace_id="trace-business-error",
        )


@pytest.mark.asyncio
async def test_mcp_transport_failures_open_shared_circuit() -> None:
    backend = FailingClient()
    protected = CircuitProtectedMCPClient(
        backend,
        AsyncCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=30),
    )

    with pytest.raises(MCPClientError) as first:
        await protected.call_tool("get_purchase_request", {"requirement_id": 1})
    with pytest.raises(MCPClientError) as blocked:
        await protected.call_tool("get_purchase_request", {"requirement_id": 1})

    assert first.value.code == "MCP_TRANSPORT_ERROR"
    assert blocked.value.code == "MCP_CIRCUIT_OPEN"
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_mcp_business_failure_does_not_trip_circuit() -> None:
    backend = BusinessFailureClient()
    protected = CircuitProtectedMCPClient(
        backend,
        AsyncCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=30),
    )

    first = await protected.call_tool("get_purchase_request", {"requirement_id": 1})
    second = await protected.call_tool("get_purchase_request", {"requirement_id": 1})

    assert first.code == "PERMISSION_DENIED"
    assert second.code == "PERMISSION_DENIED"
    assert backend.calls == 2
