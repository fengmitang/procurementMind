import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.config import AgentSettings
from agent_app.core.exceptions import AgentError
from agent_app.graph.schemas import HITLActionType, PendingAction
from agent_app.hitl.schemas import ActionResolutionStatus
from agent_app.hitl.service import HITLService
from agent_app.main import create_agent_app
from agent_app.schemas.backend import (
    BackendIdentity,
    ConversationStateData,
    RequirementMutationData,
    SnapshotSavedData,
    StateSavedData,
)


class FakeBackend:
    def __init__(self, pending: PendingAction) -> None:
        self.state = ConversationStateData(
            conversation_id=41,
            purchase_request_id=7,
            current_action="CHAT",
            collected_data={"pending_action": pending.model_dump(mode="json")},
            awaiting_confirmation=True,
        )
        self.executions = 0
        self.snapshots: list[str] = []

    async def get_conversation_state(self, *_args):
        return self.state

    async def execute_confirmed_action(self, *_args, **_kwargs):
        self.executions += 1
        await asyncio.sleep(0)
        return RequirementMutationData(requirement_id=7, status="PENDING_REVIEW", version=2)

    async def save_conversation_state(self, _identity, _conversation_id, state, _trace_id):
        self.state = ConversationStateData(conversation_id=41, **state.model_dump())
        return StateSavedData(expires_in_seconds=60)

    async def save_conversation_snapshot(
        self, _identity, _conversation_id, *, snapshot_reason, trace_id
    ):
        self.snapshots.append(snapshot_reason)
        return SnapshotSavedData(state_id=1, saved_at=datetime.now(UTC))


def pending_action(*, expired: bool = False) -> PendingAction:
    now = datetime.now(UTC)
    return PendingAction(
        action_id="a" * 32,
        confirmation_token="t" * 32,
        action_type=HITLActionType.SUBMIT_PURCHASE_REQUEST,
        draft={
            "requirement_id": 7,
            "expected_version": 1,
            "assigned_to_employee_id": 9,
        },
        created_at=now - timedelta(minutes=20) if expired else now,
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=15),
    )


@pytest.fixture
def identity() -> BackendIdentity:
    return BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="test-user-01")


@pytest.mark.asyncio
async def test_hitl_requires_explicit_confirmation_and_executes_once(identity):
    backend = FakeBackend(pending_action())
    service = HITLService(backend)  # type: ignore[arg-type]
    assert backend.executions == 0

    result = await service.confirm(
        identity,
        conversation_id=41,
        action_id="a" * 32,
        confirmation_token="t" * 32,
        trace_id="trace-1",
    )
    repeated = await service.confirm(
        identity,
        conversation_id=41,
        action_id="a" * 32,
        confirmation_token="t" * 32,
        trace_id="trace-2",
    )

    assert result.status is ActionResolutionStatus.EXECUTED
    assert repeated.status is ActionResolutionStatus.ALREADY_EXECUTED
    assert backend.executions == 1
    assert backend.state.awaiting_confirmation is False
    assert "pending_action" not in backend.state.collected_data


@pytest.mark.asyncio
async def test_hitl_cancel_and_expiry_never_execute(identity):
    canceled_backend = FakeBackend(pending_action())
    canceled = await HITLService(canceled_backend).cancel(  # type: ignore[arg-type]
        identity,
        conversation_id=41,
        action_id="a" * 32,
        confirmation_token="t" * 32,
        trace_id="trace-cancel",
    )
    expired_backend = FakeBackend(pending_action(expired=True))
    expired = await HITLService(expired_backend).confirm(  # type: ignore[arg-type]
        identity,
        conversation_id=41,
        action_id="a" * 32,
        confirmation_token="t" * 32,
        trace_id="trace-expired",
    )

    assert canceled.status is ActionResolutionStatus.CANCELED
    assert expired.status is ActionResolutionStatus.EXPIRED
    assert canceled_backend.executions == expired_backend.executions == 0


@pytest.mark.asyncio
async def test_hitl_rejects_wrong_token_and_incomplete_draft(identity):
    backend = FakeBackend(pending_action())
    service = HITLService(backend)  # type: ignore[arg-type]
    with pytest.raises(AgentError, match="确认凭证无效"):
        await service.confirm(
            identity,
            conversation_id=41,
            action_id="a" * 32,
            confirmation_token="x" * 32,
            trace_id="trace-token",
        )
    pending = pending_action()
    pending.draft = {"source_message": "创建采购申请"}
    backend = FakeBackend(pending)
    with pytest.raises(AgentError, match="缺少采购单或版本信息"):
        await HITLService(backend).confirm(  # type: ignore[arg-type]
            identity,
            conversation_id=41,
            action_id="a" * 32,
            confirmation_token="t" * 32,
            trace_id="trace-draft",
        )
    assert backend.executions == 0


@pytest.mark.asyncio
async def test_concurrent_confirmations_are_serialized(identity):
    backend = FakeBackend(pending_action())
    service = HITLService(backend)  # type: ignore[arg-type]
    results = await asyncio.gather(
        *(
            service.confirm(
                identity,
                conversation_id=41,
                action_id="a" * 32,
                confirmation_token="t" * 32,
                trace_id=f"trace-{index}",
            )
            for index in range(2)
        )
    )
    assert {result.status for result in results} == {
        ActionResolutionStatus.EXECUTED,
        ActionResolutionStatus.ALREADY_EXECUTED,
    }
    assert backend.executions == 1


@pytest.mark.asyncio
async def test_backend_action_executor_uses_allowlisted_endpoint_and_server_token():
    request_seen: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_seen
        request_seen = request
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"requirement_id": 7, "status": "PENDING_REVIEW", "version": 2},
            },
        )

    settings = AgentSettings(
        identity_gateway_secret="test-secret-with-enough-length",
        procurement_backend_url="http://backend",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://backend"
    ) as http_client:
        client = ProcurementBackendClient(settings, http_client=http_client)
        result = await client.execute_confirmed_action(
            BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="test-user-01"),
            action_type="SUBMIT_PURCHASE_REQUEST",
            action_id="a" * 32,
            draft={
                "requirement_id": 7,
                "expected_version": 1,
                "assigned_to_employee_id": 9,
            },
            trace_id="trace-execute",
        )

    assert result.version == 2
    assert request_seen is not None
    assert request_seen.url.path == "/api/v1/requirements/7/submit-review"
    assert b'"action_token":"AGENT-' in request_seen.content


@pytest.mark.asyncio
async def test_agent_confirmation_endpoint_uses_identity_bound_state():
    backend = FakeBackend(pending_action())
    application = create_agent_app(
        AgentSettings(
            identity_gateway_secret="test-secret-with-enough-length",
            procurement_backend_url="http://backend",
        ),
        backend,  # type: ignore[arg-type]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://agent"
    ) as client:
        response = await client.post(
            "/api/v1/chat/actions/confirm",
            json={
                "platform_user_id": "test-user-01",
                "conversation_id": 41,
                "action_id": "a" * 32,
                "confirmation_token": "t" * 32,
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "EXECUTED"
    assert backend.executions == 1
