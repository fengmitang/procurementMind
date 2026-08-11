from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from agent_app.clients.errors import ProcurementBackendError
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.config import AgentSettings
from agent_app.schemas.backend import BackendIdentity, ConversationStatePayload
from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.integrations.agent_state_store import AgentStateStore
from app.main import app as backend_app
from app.models.agent import AgentConversation, AgentMessage, AgentSessionState
from scripts.seed_demo_data import seed_demo_data


async def cleanup_conversation(conversation_id: int) -> None:
    await AgentStateStore().delete(conversation_id)
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(AgentSessionState).where(
                    AgentSessionState.conversation_id == conversation_id
                )
            )
            await session.execute(
                delete(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
            )
            await session.execute(
                delete(AgentConversation).where(
                    AgentConversation.conversation_id == conversation_id
                )
            )
    await engine.dispose()


def integration_settings(*, secret: str | None = None) -> AgentSettings:
    backend_settings = get_settings()
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret=secret or backend_settings.identity_gateway_secret,
        procurement_backend_url="http://backend.test",
        procurement_backend_max_retries=0,
    )


@pytest.mark.asyncio
async def test_agent_client_calls_real_backend_with_permissions_and_state_restore() -> None:
    await seed_demo_data()
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=backend_app),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(
        integration_settings(),
        http_client=http_client,
    )
    applicant = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    other_building_manager = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-07",
    )
    conversation_id: int | None = None
    try:
        ready = await client.readiness("agent-integration-ready")
        assert ready.status == "ready"

        current_user = await client.get_current_user(
            applicant,
            "agent-integration-user",
        )
        assert current_user.employee_id == 90001
        assert {role.role_code for role in current_user.roles} == {"APPLICANT"}

        requirement = await client.get_requirement(
            applicant,
            91007,
            "agent-integration-requirement",
        )
        assert requirement.requirement_no == "TEST-PR-COMPLETED-EQUAL"
        assert requirement.purchase_execution is not None
        assert requirement.purchase_execution.bank_account == "TEST****-OLD"

        timeline = await client.get_requirement_timeline(
            applicant,
            91007,
            "agent-integration-timeline",
        )
        assert timeline.items
        assert all("*" in (item.operator_mobile_masked or "*") for item in timeline.items)

        with pytest.raises(ProcurementBackendError) as denied:
            await client.get_requirement(
                other_building_manager,
                91007,
                "agent-integration-denied",
            )
        assert denied.value.status_code == 403
        assert denied.value.code == "PERMISSION_DENIED"

        with pytest.raises(ProcurementBackendError) as missing:
            await client.get_requirement(
                applicant,
                999999,
                "agent-integration-missing",
            )
        assert missing.value.status_code == 404
        assert missing.value.code == "REQUIREMENT_NOT_FOUND"

        active = await client.get_or_create_active_conversation(
            applicant,
            current_action=f"DEV01_{uuid4().hex[:8]}",
            trace_id="agent-integration-session",
        )
        conversation_id = active.conversation_id
        await client.add_conversation_message(
            applicant,
            conversation_id,
            sender_type="USER",
            content="查询 TEST 采购单",
            external_message_id=f"DEV01-{uuid4().hex}",
            trace_id="agent-integration-message",
        )
        state = ConversationStatePayload(
            purchase_request_id=91007,
            current_action="QUERY_STATUS",
            collected_data={"requirement_id": 91007},
            missing_fields=[],
        )
        await client.save_conversation_state(
            applicant,
            conversation_id,
            state,
            "agent-integration-state",
        )
        await client.save_conversation_snapshot(
            applicant,
            conversation_id,
            snapshot_reason="DEV01_TEST",
            trace_id="agent-integration-snapshot",
        )

        await AgentStateStore().delete(conversation_id)
        restored = await client.get_conversation_state(
            applicant,
            conversation_id,
            "agent-integration-restore",
        )
        assert restored.restored_from_snapshot is True
        assert restored.purchase_request_id == 91007
        assert restored.collected_data == {"requirement_id": 91007}

        completed = await client.complete_conversation(
            applicant,
            conversation_id,
            "agent-integration-complete",
            purchase_request_id=91007,
        )
        assert completed.status == "COMPLETED"
        assert completed.redis_state_deleted is True
    finally:
        if conversation_id is not None:
            await cleanup_conversation(conversation_id)
        await http_client.aclose()


@pytest.mark.asyncio
async def test_real_backend_rejects_agent_client_with_wrong_signature() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=backend_app),
        base_url="http://backend.test",
    )
    client = ProcurementBackendClient(
        integration_settings(secret="wrong-agent-gateway-secret"),
        http_client=http_client,
    )
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    try:
        with pytest.raises(ProcurementBackendError) as captured:
            await client.get_current_user(identity, "agent-wrong-signature")
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 401
    assert captured.value.code == "INVALID_IDENTITY_SIGNATURE"
