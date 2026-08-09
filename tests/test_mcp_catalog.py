import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_app.clients.errors import ProcurementBackendError
from agent_app.mcp.catalog import (
    TOOL_CATALOG,
    ToolFactKind,
    ToolNamespace,
    get_tool_descriptor,
)
from agent_app.mcp.runtime import MCPTrustedContext
from agent_app.mcp.tools import ProcurementTools
from agent_app.schemas.backend import BackendIdentity


def context() -> MCPTrustedContext:
    return MCPTrustedContext(
        identity=BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="user-1"),
        trace_id="trace-catalog",
    )


def test_catalog_logically_separates_all_whitelisted_tools() -> None:
    assert len(TOOL_CATALOG) == 11
    assert {item.namespace for item in TOOL_CATALOG.values()} == {
        ToolNamespace.PROCUREMENT,
        ToolNamespace.PRODUCT,
        ToolNamespace.SUPPLIER,
        ToolNamespace.ANALYTICS,
    }
    assert get_tool_descriptor("get_purchase_request").fact_kind is ToolFactKind.REALTIME_FACT
    assert get_tool_descriptor("query_purchase_analytics").namespace is ToolNamespace.ANALYTICS


def test_catalog_rejects_unregistered_tools() -> None:
    with pytest.raises(ValueError, match="Unknown procurement tool"):
        get_tool_descriptor("execute_sql")


def test_protocol_metadata_declares_business_boundaries() -> None:
    metadata = get_tool_descriptor("recommend_suppliers").protocol_meta["procurementMind"]
    assert metadata == {
        "namespace": "supplier",
        "factKind": "derived_analysis",
        "sourceOfTruth": "procurement_backend",
        "visibility": "backend_enforced",
        "authoritative": True,
        "ragBoundary": "not_a_knowledge_source",
        "requiresConfirmation": False,
    }


def test_mcp_layer_does_not_import_business_storage() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("agent_app/mcp").glob("*.py")
    )

    assert "app.repositories" not in source
    assert "sqlalchemy" not in source
    assert "execute_sql" not in TOOL_CATALOG


@pytest.mark.asyncio
async def test_tool_result_carries_authority_and_visibility_metadata() -> None:
    backend = SimpleNamespace()

    async def get_requirement(identity, requirement_id, trace_id):
        return {"id": requirement_id}

    backend.get_requirement = get_requirement
    result = await ProcurementTools(backend, context(), timeout_seconds=1).get_purchase_request(7)

    assert result.metadata is not None
    assert result.metadata.namespace is ToolNamespace.PROCUREMENT
    assert result.metadata.fact_kind is ToolFactKind.REALTIME_FACT
    assert result.metadata.source_of_truth == "procurement_backend"
    assert result.metadata.visibility == "backend_enforced"
    assert result.metadata.authoritative is True


@pytest.mark.asyncio
async def test_backend_and_timeout_errors_are_retry_classified() -> None:
    forbidden_backend = SimpleNamespace()

    async def forbidden(*args):
        raise ProcurementBackendError("FORBIDDEN", "forbidden", 403)

    forbidden_backend.get_requirement = forbidden
    forbidden_result = await ProcurementTools(
        forbidden_backend,
        context(),
        timeout_seconds=1,
    ).get_purchase_request(7)

    timeout_backend = SimpleNamespace()

    async def slow(*args):
        await asyncio.sleep(0.05)
        return {}

    timeout_backend.get_current_user = slow
    timeout_result = await ProcurementTools(
        timeout_backend,
        context(),
        timeout_seconds=0.001,
    ).get_current_user()

    assert forbidden_result.error is not None
    assert forbidden_result.error.category == "authorization"
    assert forbidden_result.error.retryable is False
    assert timeout_result.error is not None
    assert timeout_result.error.category == "timeout"
    assert timeout_result.error.retryable is True
