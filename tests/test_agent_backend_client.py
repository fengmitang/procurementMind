import json

import httpx
import pytest

from agent_app.clients.errors import (
    ProcurementBackendError,
    ProcurementBackendProtocolError,
    ProcurementBackendTimeout,
)
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.clients.signing import build_gateway_signature
from agent_app.core.config import AgentSettings
from agent_app.schemas.backend import BackendIdentity, ConversationStatePayload

TEST_SECRET = "test-agent-gateway-secret-value"


def settings(**overrides) -> AgentSettings:
    values = {
        "_env_file": None,
        "identity_gateway_secret": TEST_SECRET,
        "procurement_backend_url": "http://backend.test",
        "procurement_backend_retry_delay_seconds": 0,
    }
    values.update(overrides)
    return AgentSettings(**values)


def success(data: dict) -> dict:
    return {
        "success": True,
        "code": "OK",
        "message": "操作成功",
        "data": data,
        "trace_id": "backend-trace",
    }


@pytest.mark.asyncio
async def test_backend_client_signs_identity_and_propagates_trace() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-Id"] == "trace-001"
        assert request.headers["X-Platform-Type"] == "TEST_PLATFORM"
        expected = build_gateway_signature(
            secret=TEST_SECRET,
            method=request.method,
            path=request.url.path,
            platform_type=request.headers["X-Platform-Type"],
            platform_user_id=request.headers["X-Platform-User-Id"],
            timestamp=request.headers["X-Gateway-Timestamp"],
            nonce=request.headers["X-Gateway-Nonce"],
        )
        assert request.headers["X-Gateway-Signature"] == expected
        return httpx.Response(
            200,
            json=success(
                {
                    "employee_id": 90001,
                    "employee_no": "TEST-E001",
                    "name": "测试需求人",
                    "mobile": "13800009001",
                    "status": "ACTIVE",
                    "platform_type": "TEST_PLATFORM",
                    "platform_user_id": "test-user-01",
                    "roles": [
                        {
                            "role_id": 1,
                            "role_code": "APPLICANT",
                            "role_name": "需求人",
                        }
                    ],
                    "buildings": [
                        {
                            "building_id": 1,
                            "building_name": "一号楼",
                            "is_primary": True,
                        }
                    ],
                }
            ),
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(settings(), http_client=http_client)
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    try:
        user = await client.get_current_user(identity, "trace-001")
    finally:
        await http_client.aclose()

    assert user.employee_id == 90001
    assert user.roles[0].role_code == "APPLICANT"


@pytest.mark.asyncio
async def test_backend_client_wraps_all_session_endpoints() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/active"):
            data = {
                "conversation_id": 123,
                "status": "ACTIVE",
                "purchase_request_id": None,
                "redis_state_exists": True,
            }
        elif path.endswith("/messages") and request.method == "POST":
            data = {
                "message_id": 456,
                "created_at": "2026-08-04T12:00:00",
                "duplicate": False,
            }
        elif path.endswith("/messages"):
            data = {"items": [], "page": 1, "page_size": 50, "total": 0}
        elif path.endswith("/state") and request.method == "GET":
            data = {
                "conversation_id": 123,
                "purchase_request_id": None,
                "current_action": "CHAT",
                "collected_data": {},
                "missing_fields": [],
                "pending_field": None,
                "awaiting_confirmation": False,
                "recent_messages": [],
                "last_recommendations": [],
                "restored_from_snapshot": False,
            }
        elif path.endswith("/state"):
            data = {"saved": True, "expires_in_seconds": 259200}
        elif path.endswith("/snapshot"):
            data = {"state_id": 789, "saved_at": "2026-08-04T12:00:00"}
        else:
            data = {
                "conversation_id": 123,
                "status": "COMPLETED",
                "redis_state_deleted": True,
            }
        return httpx.Response(200, json=success(data))

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(settings(), http_client=http_client)
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    try:
        active = await client.get_or_create_active_conversation(
            identity,
            current_action="CHAT",
            trace_id="trace-session",
        )
        await client.add_conversation_message(
            identity,
            active.conversation_id,
            sender_type="USER",
            content="hello",
            trace_id="trace-session",
        )
        await client.list_conversation_messages(
            identity,
            active.conversation_id,
            "trace-session",
        )
        state = await client.get_conversation_state(
            identity,
            active.conversation_id,
            "trace-session",
        )
        await client.save_conversation_state(
            identity,
            active.conversation_id,
            ConversationStatePayload(current_action=state.current_action),
            "trace-session",
        )
        await client.save_conversation_snapshot(
            identity,
            active.conversation_id,
            snapshot_reason="TEST",
            trace_id="trace-session",
        )
        completed = await client.complete_conversation(
            identity,
            active.conversation_id,
            "trace-session",
        )
    finally:
        await http_client.aclose()

    assert completed.status == "COMPLETED"
    assert seen == [
        ("POST", "/api/v1/agent/conversations/active"),
        ("POST", "/api/v1/agent/conversations/123/messages"),
        ("GET", "/api/v1/agent/conversations/123/messages"),
        ("GET", "/api/v1/agent/conversations/123/state"),
        ("PUT", "/api/v1/agent/conversations/123/state"),
        ("POST", "/api/v1/agent/conversations/123/snapshot"),
        ("POST", "/api/v1/agent/conversations/123/complete"),
    ]


@pytest.mark.asyncio
async def test_backend_client_wraps_mcp_history_and_recommendation_endpoints() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/api/v1/purchase-records":
            data = {"items": [], "page": 2, "page_size": 25, "total": 0}
        else:
            data = {"items": []}
        return httpx.Response(200, json=success(data))

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(settings(), http_client=http_client)
    identity = BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="test-user-01")
    try:
        records = await client.search_purchase_records(
            identity,
            "trace-mcp",
            device_name="服务器",
            page=2,
            page_size=25,
        )
        await client.recommend_products(
            identity,
            "trace-mcp",
            device_name="服务器",
            limit=5,
        )
        await client.recommend_purchase_history(
            identity,
            "trace-mcp",
            requirement_id=7,
            limit=6,
        )
        await client.recommend_suppliers(
            identity,
            "trace-mcp",
            requirement_id=7,
            limit=4,
        )
    finally:
        await http_client.aclose()

    assert records.page == 2
    assert seen == [
        (
            "/api/v1/purchase-records",
            {"device_name": "服务器", "page": "2", "page_size": "25"},
        ),
        (
            "/api/v1/recommendations/products",
            {"device_name": "服务器", "limit": "5"},
        ),
        (
            "/api/v1/recommendations/purchase-history",
            {"requirement_id": "7", "limit": "6"},
        ),
        (
            "/api/v1/recommendations/suppliers",
            {"requirement_id": "7", "limit": "4"},
        ),
    ]


@pytest.mark.asyncio
async def test_backend_client_preserves_business_error_and_backend_trace() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "success": False,
                "code": "PERMISSION_DENIED",
                "message": "无权查看该采购申请",
                "data": None,
                "trace_id": "backend-denied-trace",
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(settings(), http_client=http_client)
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-07",
    )
    try:
        with pytest.raises(ProcurementBackendError) as captured:
            await client.get_requirement(identity, 91007, "trace-denied")
    finally:
        await http_client.aclose()

    assert captured.value.code == "PERMISSION_DENIED"
    assert captured.value.status_code == 403
    assert captured.value.backend_trace_id == "backend-denied-trace"


@pytest.mark.asyncio
async def test_backend_client_retries_read_timeout_with_bound() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(
        settings(procurement_backend_max_retries=1),
        http_client=http_client,
    )
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    try:
        with pytest.raises(ProcurementBackendTimeout):
            await client.get_current_user(identity, "trace-timeout")
    finally:
        await http_client.aclose()

    assert calls == 2


@pytest.mark.asyncio
async def test_backend_client_rejects_non_json_success_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(settings(), http_client=http_client)
    try:
        with pytest.raises(ProcurementBackendProtocolError):
            await client.readiness("trace-protocol")
    finally:
        await http_client.aclose()


def test_session_payload_is_json_serializable() -> None:
    payload = ConversationStatePayload(
        current_action="CHAT",
        collected_data={"quantity": 2, "confirmed": False},
    )

    assert json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
