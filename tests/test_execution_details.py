from contextlib import asynccontextmanager

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.schemas import RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.observability import build_execution_details
from tests.test_agent_graph import FakeMCPClient, request


def settings() -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="execution-details-test-secret",
        procurement_backend_url="http://backend.test",
    )


@pytest.mark.asyncio
async def test_execution_details_restore_graph_tool_and_usage_facts() -> None:
    client = FakeMCPClient(
        MCPToolResponse.ok(
            {
                "requirement_id": 91007,
                "requirement_no": "TEST-PR-91007",
                "status": "COMPLETED",
                "current_handler": None,
            },
            source="/api/v1/requirements/91007",
            trace_id="trace-graph",
        )
    )

    @asynccontextmanager
    async def factory(*_args):
        yield client

    result = await ProcurementGraphService(
        settings(),
        mcp_client_factory=factory,
    ).run(request("查询采购申请 91007 当前状态"))
    details = build_execution_details(
        result,
        model_configured=False,
        model_provider=None,
        model_name=None,
    )

    assert details.trace_id == "trace-graph"
    assert details.route == RouteType.REALTIME_BUSINESS.value
    assert details.status == "COMPLETE"
    assert details.duration_ms >= 0
    assert [event.name for event in details.trace_events] == [
        "load_context",
        "first_version_router",
        "get_purchase_request",
        "sufficiency_check",
        "compose_answer",
        "review",
        "confirmation",
        "finalize",
    ]
    assert details.tools[0].name == "get_purchase_request"
    assert details.tools[0].trace_id == details.trace_id
    assert details.model_usage.call_count == 0
    assert details.model_usage.total_tokens is None
    assert details.model_usage.estimated_cost is None
    assert {item.name: item.status for item in details.components} == {
        "GRAPH": "SUCCESS",
        "MCP": "SUCCESS",
        "MODEL": "SKIPPED",
        "RAG": "SKIPPED",
        "REVIEW": "SUCCESS",
    }


@pytest.mark.asyncio
async def test_execution_details_mark_unavailable_knowledge_route() -> None:
    client = FakeMCPClient(
        MCPToolResponse.failure(
            "UNUSED",
            "unused",
            source="unused",
            trace_id="trace-graph",
        )
    )

    @asynccontextmanager
    async def factory(*_args):
        yield client

    result = await ProcurementGraphService(
        settings(),
        mcp_client_factory=factory,
    ).run(request("采购流程有哪些规定"))
    details = build_execution_details(
        result,
        model_configured=False,
        model_provider=None,
        model_name=None,
    )

    assert details.status == "NOT_AVAILABLE"
    assert details.tool_call_count == 0
    assert details.tools == []
