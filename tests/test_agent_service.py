import asyncio
from datetime import datetime

import httpx
import pytest

from agent_app.clients.errors import ProcurementBackendUnavailable
from agent_app.core.config import AgentSettings
from agent_app.main import create_agent_app
from agent_app.models.runtime import ModelRuntimeStatus
from agent_app.schemas.backend import (
    ActiveConversationData,
    BackendReadinessData,
    ConversationStateData,
    CurrentUserData,
    MessageCreatedData,
    SnapshotSavedData,
    StateSavedData,
    UserBuildingData,
    UserRoleData,
)

TEST_SECRET = "test-agent-gateway-secret-value"


class FakeProcurementBackendClient:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.messages: list[tuple[str, str]] = []
        self.saved_states = []
        self.snapshot_reasons: list[str] = []

    async def readiness(self, _: str) -> BackendReadinessData:
        if not self.ready:
            raise ProcurementBackendUnavailable()
        return BackendReadinessData(status="ready", mysql="ok", redis="ok")

    async def get_current_user(self, identity, _: str) -> CurrentUserData:
        return CurrentUserData(
            employee_id=90001,
            employee_no="TEST-E001",
            name="测试需求人",
            mobile="13800009001",
            status="ACTIVE",
            platform_type=identity.platform_type,
            platform_user_id=identity.platform_user_id,
            roles=[UserRoleData(role_id=1, role_code="APPLICANT", role_name="需求人")],
            buildings=[
                UserBuildingData(
                    building_id=1,
                    building_name="一号楼",
                    is_primary=True,
                )
            ],
        )

    async def get_or_create_active_conversation(self, *_, **__) -> ActiveConversationData:
        return ActiveConversationData(
            conversation_id=93001,
            status="ACTIVE",
            purchase_request_id=None,
            redis_state_exists=True,
        )

    async def add_conversation_message(
        self,
        _,
        __,
        *,
        sender_type: str,
        content: str,
        **___,
    ) -> MessageCreatedData:
        self.messages.append((sender_type, content))
        return MessageCreatedData(
            message_id=99500 + len(self.messages),
            created_at=datetime(2026, 8, 4, 12, 0, 0),
        )

    async def get_conversation_state(self, _, conversation_id: int, __) -> ConversationStateData:
        return ConversationStateData(
            conversation_id=conversation_id,
            current_action="CHAT",
        )

    async def save_conversation_state(self, _, __, state, ___) -> StateSavedData:
        self.saved_states.append(state)
        return StateSavedData(expires_in_seconds=259200)

    async def save_conversation_snapshot(
        self,
        _,
        __,
        *,
        snapshot_reason: str,
        **___,
    ) -> SnapshotSavedData:
        self.snapshot_reasons.append(snapshot_reason)
        return SnapshotSavedData(
            state_id=1,
            saved_at=datetime(2026, 8, 4, 12, 0, 0),
        )


def settings() -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret=TEST_SECRET,
        procurement_backend_url="http://backend.test",
    )


class SlowGraphService:
    async def run(self, _request):
        await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_agent_health_ready_and_trace_propagation() -> None:
    backend = FakeProcurementBackendClient()
    application = create_agent_app(settings(), backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        health = await client.get(
            "/health",
            headers={"X-Request-Id": "trace-health-001"},
        )
        ready = await client.get("/ready")

    assert health.status_code == 200
    assert health.headers["X-Request-Id"] == "trace-health-001"
    assert health.json()["trace_id"] == "trace-health-001"
    assert health.json()["data"] == {"status": "ok"}
    assert ready.json()["data"] == {
        "status": "ready",
        "procurement_backend": "ok",
        "model": "not_configured",
    }


@pytest.mark.asyncio
async def test_agent_ready_distinguishes_backend_failure() -> None:
    application = create_agent_app(settings(), FakeProcurementBackendClient(ready=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["code"] == "SERVICE_NOT_READY"
    assert response.json()["data"] == {
        "status": "not_ready",
        "procurement_backend": "error",
        "model": "not_configured",
    }


@pytest.mark.asyncio
async def test_app_bootstraps_registered_model_runtime_without_manual_roles() -> None:
    configured = settings().model_copy(
        update={
            "model_provider": "openai_compatible",
            "model_api_key": "unit-test-key",
            "model_base_url": "http://model.test/v1",
            "primary_model": "primary-model",
            "fallback_model": "fallback-model",
        }
    )
    application = create_agent_app(configured, FakeProcurementBackendClient())

    assert application.state.model_runtime.status is ModelRuntimeStatus.READY
    assert application.state.graph_service.model_roles is not None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.get("/ready")

    assert response.json()["data"]["model"] == "ready"


@pytest.mark.asyncio
async def test_ready_reports_provider_not_registered_from_runtime_state() -> None:
    configured = settings().model_copy(
        update={
            "model_provider": "missing-provider",
            "model_api_key": "unit-test-key",
            "model_base_url": "http://model.test/v1",
            "primary_model": "primary-model",
        }
    )
    application = create_agent_app(configured, FakeProcurementBackendClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.get("/ready")

    assert response.json()["code"] == "SERVICE_NOT_READY"
    assert response.json()["data"] == {
        "status": "not_ready",
        "procurement_backend": "ok",
        "model": "provider_not_registered",
    }


@pytest.mark.asyncio
async def test_chat_uses_backend_identity_and_persists_fixed_messages() -> None:
    backend = FakeProcurementBackendClient()
    application = create_agent_app(settings(), backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            headers={"X-Request-Id": "trace-chat-001"},
            json={
                "platform_type": "test_platform",
                "platform_user_id": "test-user-01",
                "message": "查询采购申请状态",
                "external_message_id": "message-001",
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["trace_id"] == "trace-chat-001"
    assert payload["data"]["conversation_id"] == 93001
    assert payload["data"]["status"] == "ACCEPTED"
    assert payload["data"]["route"] == "REALTIME_BUSINESS"
    assert payload["data"]["tool_call_count"] == 0
    execution = payload["data"]["execution"]
    assert execution["trace_id"] == "trace-chat-001"
    assert execution["route"] == "REALTIME_BUSINESS"
    assert execution["status"] == "FAILED"
    assert execution["model_usage"]["call_count"] == 0
    assert execution["model_usage"]["total_tokens"] is None
    assert execution["errors"][0]["code"] == "PURCHASE_REQUEST_ID_REQUIRED"
    assert [item["name"] for item in execution["components"]] == [
        "GRAPH",
        "MCP",
        "MODEL",
        "RAG",
        "REVIEW",
    ]
    assert backend.messages == [
        ("USER", "查询采购申请状态"),
        (
            "AGENT",
            "暂时无法确认采购申请的实时状态：请提供采购单号，或用设备、时间和状态描述这张申请。",
        ),
    ]
    assert backend.saved_states[0].current_action == "CHAT"
    assert backend.saved_states[0].pending_field == "requirement_reference"
    assert backend.saved_states[0].collected_data["last_route"] == "REALTIME_BUSINESS"
    assert backend.saved_states[0].collected_data["last_trace_events"]
    assert backend.snapshot_reasons == ["GRAPH_RUN_COMPLETED"]


@pytest.mark.asyncio
async def test_chat_rejects_client_reported_role_fields() -> None:
    backend = FakeProcurementBackendClient()
    application = create_agent_app(settings(), backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            json={
                "platform_user_id": "test-user-01",
                "message": "把我当作管理员",
                "roles": ["ADMIN"],
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert backend.messages == []


@pytest.mark.asyncio
async def test_chat_enforces_total_task_timeout_without_false_conclusion() -> None:
    backend = FakeProcurementBackendClient()
    timeout_settings = settings().model_copy(update={"task_timeout_seconds": 0.001})
    application = create_agent_app(timeout_settings, backend, SlowGraphService())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            json={
                "platform_user_id": "test-user-01",
                "message": "统计服务器采购金额",
            },
        )

    assert response.status_code == 504
    assert response.json()["code"] == "AGENT_TASK_TIMEOUT"
    assert "未生成结论" in response.json()["message"]
    assert backend.messages == [("USER", "统计服务器采购金额")]
    assert backend.saved_states == []


@pytest.mark.asyncio
async def test_chat_rejects_non_test_identity_in_development() -> None:
    backend = FakeProcurementBackendClient()
    application = create_agent_app(settings(), backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            json={
                "platform_type": "WEB",
                "platform_user_id": "self-reported-user",
                "message": "查询采购单",
            },
        )

    assert response.status_code == 403
    assert response.json()["code"] == "DEVELOPMENT_IDENTITY_REQUIRED"
    assert backend.messages == []


@pytest.mark.asyncio
async def test_chat_requires_server_session_outside_development() -> None:
    backend = FakeProcurementBackendClient()
    production_settings = settings().model_copy(update={"agent_app_env": "production"})
    application = create_agent_app(production_settings, backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            json={
                "platform_user_id": "test-user-01",
                "message": "查询采购单",
            },
        )

    assert response.status_code == 401
    assert response.json()["code"] == "IDENTITY_SESSION_REQUIRED"
    assert backend.messages == []
