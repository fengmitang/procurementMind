import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.agent import AgentConversation, AgentMessage, AgentSessionState
from scripts.seed_demo_data import seed_demo_data


def signed_headers(method: str, path: str, platform_user_id: str) -> dict[str, str]:
    settings = get_settings()
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    platform_type = "TEST_PLATFORM"
    return {
        "X-Platform-Type": platform_type,
        "X-Platform-User-Id": platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": nonce,
        "X-Gateway-Signature": build_gateway_signature(
            secret=settings.identity_gateway_secret,
            method=method,
            path=path,
            platform_type=platform_type,
            platform_user_id=platform_user_id,
            timestamp=timestamp,
            nonce=nonce,
        ),
    }


async def call(
    client: AsyncClient,
    method: str,
    path: str,
    platform_user_id: str,
    **kwargs,
):
    return await client.request(
        method,
        path,
        headers=signed_headers(method, path, platform_user_id),
        **kwargs,
    )


async def delete_redis_state(conversation_id: int) -> None:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.delete(f"agent:session:{conversation_id}")
    finally:
        await client.aclose()


async def cleanup_conversation(conversation_id: int) -> None:
    await delete_redis_state(conversation_id)
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


@pytest.mark.asyncio
async def test_external_conversations_are_distinct_listed_and_restore_message_data() -> None:
    created_ids: list[int] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            for suffix in ("A", "B"):
                response = await call(
                    client,
                    "POST",
                    "/api/v1/agent/conversations/active",
                    "test-user-01",
                    json={
                        "current_action": "CHAT",
                        "external_conversation_id": f"TEST-CHAT-{suffix}-{uuid4().hex}",
                    },
                )
                assert response.status_code == 200, response.text
                created_ids.append(response.json()["data"]["conversation_id"])
            assert created_ids[0] != created_ids[1]

            message_data = {
                "route": "REALTIME_BUSINESS",
                "business_results": [{"kind": "PURCHASE_REQUIREMENTS", "items": []}],
            }
            stored = await call(
                client,
                "POST",
                f"/api/v1/agent/conversations/{created_ids[0]}/messages",
                "test-user-01",
                json={
                    "sender_type": "AGENT",
                    "content": "已找到采购申请。",
                    "message_data": message_data,
                },
            )
            assert stored.status_code == 200, stored.text

            listed = await call(client, "GET", "/api/v1/agent/conversations", "test-user-01")
            assert listed.status_code == 200, listed.text
            listed_ids = {item["conversation_id"] for item in listed.json()["data"]["items"]}
            assert set(created_ids).issubset(listed_ids)

            restored = await call(
                client,
                "GET",
                f"/api/v1/agent/conversations/{created_ids[0]}/messages",
                "test-user-01",
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["data"]["items"][0]["message_data"] == message_data
        finally:
            for conversation_id in created_ids:
                await cleanup_conversation(conversation_id)


@pytest.fixture(autouse=True)
async def reset_demo_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    for conversation_id in range(93001, 93005):
        await delete_redis_state(conversation_id)
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_restores_existing_mysql_snapshot_when_redis_is_empty() -> None:
    state_path = "/api/v1/agent/conversations/93001/state"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        restored = await call(
            client,
            "GET",
            state_path,
            "test-user-01",
        )
        assert restored.status_code == 200, restored.text
        data = restored.json()["data"]
        assert data["conversation_id"] == 93001
        assert data["current_action"] == "CREATE_REQUEST"
        assert data["collected_data"]["quantity"] == 1
        assert data["missing_fields"] == ["application_reason"]
        assert data["restored_from_snapshot"] is True

        cached = await call(
            client,
            "GET",
            state_path,
            "test-user-01",
        )
        assert cached.status_code == 200
        assert cached.json()["data"]["restored_from_snapshot"] is False


@pytest.mark.asyncio
async def test_agent_backend_session_message_state_snapshot_and_completion() -> None:
    conversation_id: int | None = None
    action = f"TEST_ACTION_{uuid4().hex[:8]}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        try:
            active_path = "/api/v1/agent/conversations/active"
            created = await call(
                client,
                "POST",
                active_path,
                "test-user-01",
                json={
                    "current_action": action,
                    "external_conversation_id": f"TEST-EXTERNAL-{uuid4().hex}",
                },
            )
            assert created.status_code == 200, created.text
            conversation_id = created.json()["data"]["conversation_id"]
            assert created.json()["data"]["status"] == "ACTIVE"
            assert created.json()["data"]["redis_state_exists"] is True

            reused = await call(
                client,
                "POST",
                active_path,
                "test-user-01",
                json={"current_action": action},
            )
            assert reused.status_code == 200
            assert reused.json()["data"]["conversation_id"] == conversation_id

            messages_path = f"/api/v1/agent/conversations/{conversation_id}/messages"
            external_message_id = f"TEST-MESSAGE-{uuid4().hex}"
            message_payload = {
                "external_message_id": external_message_id,
                "sender_type": "USER",
                "content": "我要采购五台交换机",
            }
            message = await call(
                client,
                "POST",
                messages_path,
                "test-user-01",
                json=message_payload,
            )
            assert message.status_code == 200, message.text
            assert message.json()["data"]["duplicate"] is False
            message_id = message.json()["data"]["message_id"]

            duplicate = await call(
                client,
                "POST",
                messages_path,
                "test-user-01",
                json=message_payload,
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["data"] == {
                "message_id": message_id,
                "created_at": message.json()["data"]["created_at"],
                "duplicate": True,
            }

            denied = await call(
                client,
                "GET",
                messages_path,
                "test-user-02",
            )
            assert denied.status_code == 403

            messages = await call(
                client,
                "GET",
                messages_path,
                "test-user-01",
            )
            assert messages.status_code == 200
            assert messages.json()["data"]["total"] == 1
            assert messages.json()["data"]["items"][0]["content"] == "我要采购五台交换机"

            state_path = f"/api/v1/agent/conversations/{conversation_id}/state"
            state_payload = {
                "purchase_request_id": 91001,
                "current_action": action,
                "collected_data": {
                    "device_name": "交换机",
                    "quantity": "5",
                },
                "missing_fields": ["brand", "model"],
                "pending_field": "brand",
                "awaiting_confirmation": False,
                "recent_messages": [{"sender_type": "USER", "content": "采购交换机"}],
                "last_recommendations": [{"brand": "华为", "model": "S5735"}],
            }
            saved = await call(
                client,
                "PUT",
                state_path,
                "test-user-01",
                json=state_payload,
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["data"]["expires_in_seconds"] == 259200

            snapshot_path = f"/api/v1/agent/conversations/{conversation_id}/snapshot"
            snapshot = await call(
                client,
                "POST",
                snapshot_path,
                "test-user-01",
                json={"snapshot_reason": "HITL_EXECUTED"},
            )
            assert snapshot.status_code == 200, snapshot.text

            async with async_session_factory() as session:
                confirmed_snapshot = await session.scalar(
                    select(AgentSessionState).where(
                        AgentSessionState.conversation_id == conversation_id
                    )
                )
                assert confirmed_snapshot is not None
                assert confirmed_snapshot.confirmed is True

            await delete_redis_state(conversation_id)
            restored = await call(
                client,
                "GET",
                state_path,
                "test-user-01",
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["data"]["restored_from_snapshot"] is True
            assert restored.json()["data"]["collected_data"] == {
                "device_name": "交换机",
                "quantity": "5",
            }
            assert restored.json()["data"]["last_recommendations"] == [
                {"brand": "华为", "model": "S5735"}
            ]

            complete_path = f"/api/v1/agent/conversations/{conversation_id}/complete"
            completed = await call(
                client,
                "POST",
                complete_path,
                "test-user-01",
                json={"purchase_request_id": 91001},
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["data"]["status"] == "COMPLETED"
            assert completed.json()["data"]["redis_state_deleted"] is True

            state_after_complete = await call(
                client,
                "GET",
                state_path,
                "test-user-01",
            )
            assert state_after_complete.status_code == 409
            assert state_after_complete.json()["code"] == "INVALID_SESSION_STATUS"

            async with async_session_factory() as session:
                conversation = await session.get(
                    AgentConversation,
                    conversation_id,
                )
                snapshot_row = await session.scalar(
                    select(AgentSessionState).where(
                        AgentSessionState.conversation_id == conversation_id
                    )
                )
                assert conversation is not None
                assert snapshot_row is not None
                assert conversation.status == "COMPLETED"
                assert conversation.purchase_request_id == 91001
                assert snapshot_row.state_data["snapshot_reason"] == "SESSION_COMPLETED"
        finally:
            if conversation_id is not None:
                await cleanup_conversation(conversation_id)
