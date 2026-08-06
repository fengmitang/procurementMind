import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_app.core.config import AgentSettings
from agent_app.mcp.client import MCPClientError, ProcurementMCPClient
from agent_app.schemas.backend import BackendIdentity

EXPECTED_TOOLS = {
    "get_current_user",
    "get_purchase_request",
    "get_purchase_timeline",
    "search_purchase_records",
    "recommend_products",
    "recommend_purchase_history",
    "recommend_suppliers",
    "query_purchase_analytics",
    "get_requirement_risk_signals",
    "get_similar_cases",
    "get_supplier_performance",
}


class CurrentUserHandler(BaseHTTPRequestHandler):
    received_headers: dict[str, str] = {}

    def do_GET(self) -> None:
        type(self).received_headers = {key: value for key, value in self.headers.items()}
        payload = {
            "success": True,
            "code": "OK",
            "message": "success",
            "data": {
                "employee_id": 1,
                "employee_no": "E001",
                "name": "MCP 测试用户",
                "mobile": "138****0000",
                "status": "ACTIVE",
                "platform_type": "TEST_PLATFORM",
                "platform_user_id": "mcp-user",
                "roles": [],
                "buildings": [],
            },
            "trace_id": self.headers.get("X-Request-Id"),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


@pytest.fixture
def backend_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CurrentUserHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def settings(
    backend_url: str,
    *,
    timeout: float = 20,
    startup_timeout: float = 60,
) -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="mcp-contract-secret-123456",
        procurement_backend_url=backend_url,
        procurement_backend_max_retries=0,
        mcp_startup_timeout_seconds=startup_timeout,
        mcp_tool_timeout_seconds=timeout,
    )


def identity() -> BackendIdentity:
    return BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="mcp-user")


@pytest.mark.asyncio
async def test_standard_stdio_handshake_discovery_call_and_trace(backend_url: str) -> None:
    async with ProcurementMCPClient(
        settings(backend_url),
        identity(),
        "trace-mcp-contract",
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool("get_current_user")

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        properties = tool.inputSchema.get("properties", {})
        assert "platform_type" not in properties
        assert "platform_user_id" not in properties
        assert "trace_id" not in properties
    assert result.success is True
    assert result.trace_id == "trace-mcp-contract"
    assert result.data["name"] == "MCP 测试用户"
    assert CurrentUserHandler.received_headers["X-Platform-User-Id"] == "mcp-user"
    assert CurrentUserHandler.received_headers["X-Request-Id"] == "trace-mcp-contract"
    assert "X-Gateway-Signature" in CurrentUserHandler.received_headers


@pytest.mark.asyncio
async def test_protocol_rejects_unknown_tools_and_invalid_arguments(
    backend_url: str,
) -> None:
    async with ProcurementMCPClient(
        settings(backend_url),
        identity(),
        "trace-mcp-invalid",
    ) as client:
        invalid_calls = [
            ("missing_tool", {}),
            ("get_purchase_request", {"requirement_id": 0}),
            ("recommend_products", {"device_name": ""}),
            ("query_purchase_analytics", {"query": {"building_ids": [0]}}),
        ]
        for name, arguments in invalid_calls:
            with pytest.raises(MCPClientError) as exc_info:
                await client.call_tool(name, arguments)
            assert exc_info.value.code == "MCP_PROTOCOL_TOOL_ERROR"


@pytest.mark.asyncio
async def test_subprocess_failure_is_classified(backend_url: str) -> None:
    client = ProcurementMCPClient(
        settings(backend_url, startup_timeout=0.5),
        identity(),
        "trace-mcp-process",
        command="procurement-mind-command-does-not-exist",
    )

    with pytest.raises(MCPClientError) as exc_info:
        async with client:
            pass

    assert exc_info.value.code == "MCP_SUBPROCESS_ERROR"
