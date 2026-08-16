import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete

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
from app.core.config import get_settings as get_backend_settings
from app.db.session import async_session_factory, engine
from app.main import app as backend_app
from app.models.notification import NotificationOutbox
from app.models.procurement import PurchaseOperationLog, PurchaseRequest
from scripts.seed_demo_data import seed_demo_data


class FakeBackend:
    def __init__(
        self,
        pending: PendingAction,
        *,
        result: RequirementMutationData | None = None,
    ) -> None:
        self.state = ConversationStateData(
            conversation_id=41,
            purchase_request_id=(
                None
                if pending.action_type is HITLActionType.CREATE_PURCHASE_DRAFT
                else 7
            ),
            current_action="CHAT",
            collected_data={
                "pending_action": pending.model_dump(mode="json"),
                "form_draft": pending.draft,
                "form_missing_fields": [],
            },
            awaiting_confirmation=True,
        )
        self.result = result or RequirementMutationData(
            requirement_id=7,
            status="PENDING_REVIEW",
            version=2,
        )
        self.executions = 0
        self.snapshots: list[str] = []

    async def get_conversation_state(self, *_args):
        return self.state

    async def execute_confirmed_action(self, *_args, **_kwargs):
        self.executions += 1
        await asyncio.sleep(0)
        return self.result

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


def create_draft_action() -> PendingAction:
    return PendingAction(
        action_id="d" * 32,
        confirmation_token="c" * 32,
        action_type=HITLActionType.CREATE_PURCHASE_DRAFT,
        draft={
            "building_id": 1,
            "device_profession": "服务器",
            "device_name": "浪潮服务器",
            "brand": "浪潮",
            "quantity": 3,
            "unit": "台",
            "application_reason": "替换故障设备",
        },
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
async def test_create_draft_confirmation_binds_requirement_and_clears_form_state(identity):
    backend = FakeBackend(
        create_draft_action(),
        result=RequirementMutationData(
            requirement_id=12345,
            requirement_no="PR-TEST-HITL",
            status="DRAFT",
            version=1,
        ),
    )

    result = await HITLService(backend).confirm(  # type: ignore[arg-type]
        identity,
        conversation_id=41,
        action_id="d" * 32,
        confirmation_token="c" * 32,
        trace_id="trace-create-draft",
    )

    assert result.status is ActionResolutionStatus.EXECUTED
    assert result.result is not None
    assert result.result["requirement_id"] == 12345
    assert result.result["requirement_no"] == "PR-TEST-HITL"
    assert result.result["status"] == "DRAFT"
    assert backend.state.purchase_request_id == 12345
    assert backend.state.awaiting_confirmation is False
    assert backend.state.missing_fields == []
    assert backend.state.pending_field is None
    assert "pending_action" not in backend.state.collected_data
    assert "form_draft" not in backend.state.collected_data
    assert "form_missing_fields" not in backend.state.collected_data
    assert backend.snapshots == ["HITL_EXECUTED"]


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
        _env_file=None,
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
async def test_backend_action_executor_creates_and_populates_purchase_draft(identity):
    requests_seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.method == "POST" and request.url.path == "/api/v1/requirements":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "requirement_id": 12345,
                        "requirement_no": "PR-TEST-HITL",
                        "status": "DRAFT",
                        "version": 0,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "requirement_id": 12345,
                    "status": "DRAFT",
                    "version": 1,
                    "missing_fields": [],
                    "next_missing_field": None,
                    "fields_complete": True,
                },
            },
        )

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="test-secret-with-enough-length",
        procurement_backend_url="http://backend",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://backend"
    ) as http_client:
        client = ProcurementBackendClient(settings, http_client=http_client)
        result = await client.execute_confirmed_action(
            identity,
            action_type="CREATE_PURCHASE_DRAFT",
            action_id="d" * 32,
            draft=create_draft_action().draft,
            trace_id="trace-create-draft",
        )

    assert result.requirement_id == 12345
    assert result.requirement_no == "PR-TEST-HITL"
    assert result.status == "DRAFT"
    assert [request.method for request in requests_seen] == ["POST", "PATCH"]
    assert [request.url.path for request in requests_seen] == [
        "/api/v1/requirements",
        "/api/v1/requirements/12345/applicant-fields",
    ]
    assert requests_seen[0].read() == b'{"building_id":1}'
    saved_payload = requests_seen[1].read().decode("utf-8")
    assert '"expected_version":0' in saved_payload
    assert '"device_name":"浪潮服务器"' in saved_payload
    assert '"application_reason":"替换故障设备"' in saved_payload


@pytest.mark.asyncio
async def test_create_draft_hitl_flow_persists_real_database_draft(identity):
    request_id: int | None = None
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()
    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret=get_backend_settings().identity_gateway_secret,
        procurement_backend_url="http://backend",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=backend_app),
        base_url="http://backend",
    ) as http_client:
        real_client = ProcurementBackendClient(settings, http_client=http_client)
        state_backend = FakeBackend(create_draft_action())
        state_backend.execute_confirmed_action = real_client.execute_confirmed_action  # type: ignore[method-assign]
        try:
            result = await HITLService(state_backend).confirm(  # type: ignore[arg-type]
                identity,
                conversation_id=41,
                action_id="d" * 32,
                confirmation_token="c" * 32,
                trace_id="trace-real-create-draft",
            )
            assert result.result is not None
            request_id = int(result.result["requirement_id"])

            await engine.dispose()
            async with async_session_factory() as session:
                row = await session.get(PurchaseRequest, request_id)
                assert row is not None
                assert row.request_no == result.result["requirement_no"]
                assert row.status == "DRAFT"
                assert row.building_id == 1
                assert row.device_profession == "服务器"
                assert row.device_name == "浪潮服务器"
                assert row.brand == "浪潮"
                assert row.quantity == 3
                assert row.unit == "台"
                assert row.application_reason == "替换故障设备"
            assert state_backend.state.purchase_request_id == request_id
        finally:
            if request_id is not None:
                await engine.dispose()
                async with async_session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            delete(NotificationOutbox).where(
                                NotificationOutbox.request_id == request_id
                            )
                        )
                        await session.execute(
                            delete(PurchaseOperationLog).where(
                                PurchaseOperationLog.request_id == request_id
                            )
                        )
                        await session.execute(
                            delete(PurchaseRequest).where(
                                PurchaseRequest.request_id == request_id
                            )
                        )
                await engine.dispose()


@pytest.mark.asyncio
async def test_agent_confirmation_endpoint_uses_identity_bound_state():
    backend = FakeBackend(pending_action())
    application = create_agent_app(
        AgentSettings(
            _env_file=None,
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
