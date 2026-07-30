"""Run non-destructive real-HTTP smoke checks against a local backend."""

import asyncio
import os
import time
from uuid import uuid4

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.models.agent import AgentConversation, AgentMessage, AgentSessionState


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


async def request(
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


async def cleanup_conversation(conversation_id: int) -> None:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.delete(f"agent:session:{conversation_id}")
    finally:
        await redis.aclose()
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


async def main() -> None:
    base_url = os.getenv("LIVE_HTTP_BASE_URL", "http://127.0.0.1:8010")
    conversation_id: int | None = None
    checks: list[str] = []
    async with AsyncClient(base_url=base_url, timeout=10) as client:
        try:
            health = await client.get("/health")
            assert health.status_code == 200
            checks.append("health")

            ready = await client.get("/ready")
            assert ready.status_code == 200
            assert ready.json()["data"]["status"] == "ready"
            checks.append("mysql+redis")

            unauthenticated = await client.get("/api/v1/users/me")
            assert unauthenticated.status_code == 401
            checks.append("unsigned-request-rejected")

            current_user = await request(
                client,
                "GET",
                "/api/v1/users/me",
                "test-user-01",
            )
            assert current_user.status_code == 200
            assert current_user.json()["data"]["employee_id"] == 90001
            checks.append("signed-identity")

            records = await request(
                client,
                "GET",
                "/api/v1/purchase-records",
                "test-user-01",
                params={"supplier_id": 92002},
            )
            assert records.status_code == 200
            assert records.json()["data"]["total"] == 1
            checks.append("purchase-records")

            timeline = await request(
                client,
                "GET",
                "/api/v1/requirements/91007/timeline",
                "test-user-01",
            )
            assert timeline.status_code == 200
            assert timeline.json()["data"]["items"]
            checks.append("timeline")

            suppliers = await request(
                client,
                "GET",
                "/api/v1/suppliers",
                "test-user-01",
                params={"keyword": "TEST-常规"},
            )
            assert suppliers.status_code == 200
            assert suppliers.json()["data"]["total"] == 1
            checks.append("suppliers")

            active = await request(
                client,
                "POST",
                "/api/v1/agent/conversations/active",
                "test-user-01",
                json={"current_action": f"LIVE_HTTP_{uuid4().hex[:8]}"},
            )
            assert active.status_code == 200
            conversation_id = active.json()["data"]["conversation_id"]
            state_path = f"/api/v1/agent/conversations/{conversation_id}/state"
            state = await request(
                client,
                "GET",
                state_path,
                "test-user-01",
            )
            assert state.status_code == 200
            checks.append("agent-session-state")

            completed = await request(
                client,
                "POST",
                f"/api/v1/agent/conversations/{conversation_id}/complete",
                "test-user-01",
                json={},
            )
            assert completed.status_code == 200
            checks.append("agent-session-complete")

            notifications = await request(
                client,
                "GET",
                "/api/v1/notifications",
                "test-user-05",
                params={"status": "FAILED"},
            )
            assert notifications.status_code == 200
            checks.append("admin-notifications")
        finally:
            if conversation_id is not None:
                await cleanup_conversation(conversation_id)

    print(f"live_http_checks={len(checks)}")
    print("\n".join(checks))


if __name__ == "__main__":
    asyncio.run(main())
