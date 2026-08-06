import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from agent_app.clients.errors import ProcurementBackendError
from agent_app.mcp.runtime import MCPTrustedContext
from agent_app.mcp.tools import ProcurementTools
from agent_app.schemas.analytics import AnalyticsQueryInput
from agent_app.schemas.backend import BackendIdentity, CurrentUserData


def trusted_context() -> MCPTrustedContext:
    return MCPTrustedContext(
        identity=BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="user-1"),
        trace_id="trace-mcp-unit",
    )


def current_user() -> CurrentUserData:
    return CurrentUserData(
        employee_id=1,
        employee_no="E001",
        name="测试用户",
        mobile="138****0000",
        status="ACTIVE",
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
        roles=[],
        buildings=[],
    )


@pytest.mark.asyncio
async def test_tool_uses_trusted_identity_and_returns_standard_envelope() -> None:
    backend = SimpleNamespace()

    async def get_current_user(identity, trace_id):
        assert identity.platform_user_id == "user-1"
        assert trace_id == "trace-mcp-unit"
        return current_user()

    backend.get_current_user = get_current_user
    tools = ProcurementTools(backend, trusted_context(), timeout_seconds=1)

    result = await tools.get_current_user()

    assert result.success is True
    assert result.code == "OK"
    assert result.source == "/api/v1/users/me"
    assert result.trace_id == "trace-mcp-unit"
    assert result.data["employee_id"] == 1
    assert result.partial is False
    assert result.warnings == []


@pytest.mark.asyncio
async def test_tool_classifies_backend_failure_without_guessing_data() -> None:
    backend = SimpleNamespace()

    async def get_requirement(identity, requirement_id, trace_id):
        raise ProcurementBackendError("FORBIDDEN", "无权查看该采购申请", 403)

    backend.get_requirement = get_requirement
    tools = ProcurementTools(backend, trusted_context(), timeout_seconds=1)

    result = await tools.get_purchase_request(99)

    assert result.success is False
    assert result.code == "FORBIDDEN"
    assert result.data is None
    assert result.warnings == ["无权查看该采购申请"]


@pytest.mark.asyncio
async def test_tool_timeout_is_structured() -> None:
    backend = SimpleNamespace()

    async def get_current_user(identity, trace_id):
        await asyncio.sleep(0.05)
        return current_user()

    backend.get_current_user = get_current_user
    tools = ProcurementTools(backend, trusted_context(), timeout_seconds=0.001)

    result = await tools.get_current_user()

    assert result.success is False
    assert result.code == "MCP_TOOL_TIMEOUT"
    assert result.data is None


@pytest.mark.asyncio
async def test_all_eleven_whitelisted_tools_return_structured_results() -> None:
    class FakeBackend:
        async def get_current_user(self, *args, **kwargs):
            return {"kind": "user"}

        async def get_requirement(self, *args, **kwargs):
            return {"kind": "request"}

        async def get_requirement_timeline(self, *args, **kwargs):
            return {"kind": "timeline"}

        async def search_purchase_records(self, *args, **kwargs):
            return {"kind": "records"}

        async def recommend_products(self, *args, **kwargs):
            return {"kind": "products"}

        async def recommend_purchase_history(self, *args, **kwargs):
            return {"kind": "history"}

        async def recommend_suppliers(self, *args, **kwargs):
            return {"kind": "suppliers"}

        async def query_purchase_analytics(self, *args, **kwargs):
            return {"kind": "analytics"}

        async def get_requirement_risk_signals(self, *args, **kwargs):
            return {"kind": "risks"}

        async def get_similar_cases(self, *args, **kwargs):
            return {"kind": "cases"}

        async def get_supplier_performance(self, *args, **kwargs):
            return {"kind": "performance"}

    tools = ProcurementTools(FakeBackend(), trusted_context(), timeout_seconds=1)
    results = [
        await tools.get_current_user(),
        await tools.get_purchase_request(1),
        await tools.get_purchase_timeline(1),
        await tools.search_purchase_records(device_name="服务器"),
        await tools.recommend_products(device_name="服务器"),
        await tools.recommend_purchase_history(requirement_id=1),
        await tools.recommend_suppliers(requirement_id=1),
        await tools.query_purchase_analytics(AnalyticsQueryInput(device_name="服务器")),
        await tools.get_requirement_risk_signals(1),
        await tools.get_similar_cases(1),
        await tools.get_supplier_performance(1),
    ]

    assert all(result.success for result in results)
    assert [result.data["kind"] for result in results] == [
        "user",
        "request",
        "timeline",
        "records",
        "products",
        "history",
        "suppliers",
        "analytics",
        "risks",
        "cases",
        "performance",
    ]


@pytest.mark.asyncio
async def test_purchase_record_date_range_is_bounded_without_backend_call() -> None:
    backend = SimpleNamespace()
    tools = ProcurementTools(backend, trusted_context(), timeout_seconds=1)

    result = await tools.search_purchase_records(
        created_from=date(2024, 1, 1),
        created_to=date(2026, 1, 2),
    )

    assert result.success is False
    assert result.code == "MCP_INVALID_ARGUMENT"
