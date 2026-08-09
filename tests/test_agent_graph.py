from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.router import FirstVersionRouter
from agent_app.graph.schemas import GraphRunRequest, RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.mcp.client import MCPClientError
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.schemas.backend import (
    BackendIdentity,
    ConversationStateData,
    CurrentUserData,
)


def settings(**overrides) -> AgentSettings:
    values = {
        "identity_gateway_secret": "graph-test-gateway-secret",
        "procurement_backend_url": "http://backend.test",
    }
    values.update(overrides)
    return AgentSettings(_env_file=None, **values)


def current_user() -> CurrentUserData:
    return CurrentUserData(
        employee_id=1,
        employee_no="E001",
        name="需求人",
        mobile="138****0000",
        status="ACTIVE",
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
        roles=[],
        buildings=[],
    )


def request(message: str, restored_state: ConversationStateData | None = None) -> GraphRunRequest:
    return GraphRunRequest(
        task_id=uuid4(),
        trace_id="trace-graph",
        conversation_id=1,
        identity=BackendIdentity(
            platform_type="TEST_PLATFORM",
            platform_user_id="user-1",
        ),
        current_user=current_user(),
        message=message,
        restored_state=restored_state,
    )


def requirement_response(*, success: bool = True) -> MCPToolResponse:
    if not success:
        return MCPToolResponse.failure(
            "PERMISSION_DENIED",
            "无权查看该采购申请",
            source="/api/v1/requirements/91007",
            trace_id="trace-graph",
        )
    return MCPToolResponse.ok(
        {
            "requirement_id": 91007,
            "requirement_no": "TEST-PR-91007",
            "status": "COMPLETED",
            "current_handler": None,
        },
        source="/api/v1/requirements/91007",
        trace_id="trace-graph",
    )


class FakeMCPClient:
    def __init__(self, response: MCPToolResponse | MCPClientError) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls.append((name, arguments or {}))
        if isinstance(self.response, MCPClientError):
            raise self.response
        return self.response


def factory_for(client: FakeMCPClient):
    @asynccontextmanager
    async def factory(_settings, _identity, _trace_id):
        yield client

    return factory


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("采购流程有哪些规定", RouteType.KNOWLEDGE),
        ("查询采购申请 91007 当前状态", RouteType.REALTIME_BUSINESS),
        ("为什么采购申请 91007 还不能提交", RouteType.HYBRID),
        ("统计各楼宇采购金额趋势", RouteType.COMPLEX_QUERY),
        ("调查供应商黑名单风险", RouteType.RISK_INVESTIGATION),
    ],
)
def test_first_router_distinguishes_five_routes(message: str, expected: RouteType) -> None:
    assert FirstVersionRouter().classify(message) is expected


@pytest.mark.asyncio
async def test_graph_queries_realtime_request_and_records_trace() -> None:
    mcp = FakeMCPClient(requirement_response())
    service = ProcurementGraphService(settings(), mcp_client_factory=factory_for(mcp))

    result = await service.run(request("查询采购申请 91007 当前状态和下一处理人"))

    assert result.route is RouteType.REALTIME_BUSINESS
    assert result.purchase_request_id == 91007
    assert "COMPLETED" in result.reply
    assert "暂无" in result.reply
    assert result.tool_call_count == 1
    assert result.tool_results[0].success is True
    assert result.evidence[0].reference_id == "91007"
    assert [event.name for event in result.trace_events] == [
        "load_context",
        "first_version_router",
        "get_purchase_request",
        "sufficiency_check",
        "compose_answer",
        "review",
        "confirmation",
        "finalize",
    ]
    assert mcp.calls == [("get_purchase_request", {"requirement_id": 91007})]


@pytest.mark.asyncio
async def test_graph_recovers_request_id_from_backend_conversation_state() -> None:
    restored = ConversationStateData(
        conversation_id=1,
        purchase_request_id=91007,
        current_action="REALTIME_BUSINESS",
        collected_data={"requirement_id": 91007},
        restored_from_snapshot=True,
    )
    mcp = FakeMCPClient(requirement_response())
    service = ProcurementGraphService(settings(), mcp_client_factory=factory_for(mcp))
    graph_request = request("查询当前采购单状态", restored)

    result = await service.run(graph_request)
    backend_state = GraphMemoryMapper.to_backend_state(graph_request, result)

    assert result.restored_from_snapshot is True
    assert result.purchase_request_id == 91007
    assert backend_state.purchase_request_id == 91007
    assert backend_state.collected_data["last_route"] == "REALTIME_BUSINESS"
    assert backend_state.collected_data["last_trace_events"]
    assert backend_state.recent_messages[-1]["sender_type"] == "AGENT"


@pytest.mark.asyncio
async def test_graph_requests_missing_id_without_calling_tool() -> None:
    mcp = FakeMCPClient(requirement_response())
    service = ProcurementGraphService(settings(), mcp_client_factory=factory_for(mcp))

    result = await service.run(request("查询当前采购单状态"))

    assert result.errors[0].code == "PURCHASE_REQUEST_ID_REQUIRED"
    assert "请提供采购申请 ID" in result.reply
    assert result.tool_call_count == 0
    assert mcp.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (requirement_response(success=False), "PERMISSION_DENIED"),
        (MCPClientError("MCP_TOOL_TIMEOUT", "工具调用超时"), "MCP_TOOL_TIMEOUT"),
    ],
)
async def test_graph_controls_permission_and_transport_failures(
    response: MCPToolResponse | MCPClientError,
    expected_code: str,
) -> None:
    mcp = FakeMCPClient(response)
    service = ProcurementGraphService(settings(), mcp_client_factory=factory_for(mcp))

    result = await service.run(request("查询采购申请 91007 当前状态"))

    assert result.errors[0].code == expected_code
    assert result.tool_results[0].data is None
    assert "暂时无法确认" in result.reply


@pytest.mark.asyncio
async def test_graph_step_limit_stops_before_tool_call() -> None:
    mcp = FakeMCPClient(requirement_response())
    service = ProcurementGraphService(
        settings(max_execution_steps=1),
        mcp_client_factory=factory_for(mcp),
    )

    result = await service.run(request("查询采购申请 91007 当前状态"))

    assert result.step_count == 1
    assert result.errors[0].code == "GRAPH_STEP_LIMIT"
    assert mcp.calls == []


def test_model_configuration_can_remain_empty_without_secret() -> None:
    configured = settings()

    assert configured.model_provider is None
    assert configured.primary_model is None
    assert configured.model_api_key is None
    assert configured.model_configured is False
