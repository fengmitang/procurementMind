import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.notification import NotificationOutbox
from app.models.procurement import PurchaseOperationLog
from app.services.notifications import NotificationService
from scripts.seed_demo_data import seed_demo_data


class SuccessfulSender:
    def __init__(self) -> None:
        self.notification_ids: list[int] = []

    async def send(self, notification: NotificationOutbox) -> None:
        self.notification_ids.append(notification.notification_id)


class FailingSender:
    async def send(self, notification: NotificationOutbox) -> None:
        raise RuntimeError(f"TEST SEND FAILED {notification.notification_id}")


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


@pytest.fixture(autouse=True)
async def reset_demo_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatches_pending_and_due_failed_notifications() -> None:
    sender = SuccessfulSender()
    async with async_session_factory() as session:
        async with session.begin():
            result = await NotificationService(sender=sender).dispatch_due(session)

    assert result.claimed == 2
    assert result.sent == 2
    assert result.failed == 0
    assert sender.notification_ids == [99701, 99703]

    async with async_session_factory() as session:
        notifications = {
            item.notification_id: item
            for item in (
                await session.scalars(
                    select(NotificationOutbox).where(
                        NotificationOutbox.notification_id.in_([99701, 99703])
                    )
                )
            ).all()
        }
        assert notifications[99701].status == "SENT"
        assert notifications[99703].status == "SENT"
        assert notifications[99701].sent_at is not None
        assert notifications[99703].next_retry_at is None
        assert notifications[99703].last_error is None


@pytest.mark.asyncio
async def test_failure_uses_backoff_and_stops_at_retry_limit() -> None:
    now = datetime.now().replace(microsecond=0)
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.notification_id == 99703)
                .values(
                    retry_count=4,
                    next_retry_at=now - timedelta(seconds=1),
                )
            )

    async with async_session_factory() as session:
        async with session.begin():
            result = await NotificationService(sender=FailingSender()).dispatch_due(session)

    assert result.claimed == 2
    assert result.failed == 2
    assert result.exhausted == 1

    async with async_session_factory() as session:
        pending_failure = await session.get(NotificationOutbox, 99701)
        exhausted_failure = await session.get(NotificationOutbox, 99703)
        assert pending_failure is not None
        assert exhausted_failure is not None
        assert pending_failure.status == "FAILED"
        assert pending_failure.retry_count == 1
        assert pending_failure.next_retry_at is not None
        assert 55 <= (pending_failure.next_retry_at - now).total_seconds() <= 65
        assert "TEST SEND FAILED" in pending_failure.last_error
        assert exhausted_failure.retry_count == 5
        assert exhausted_failure.next_retry_at is None


@pytest.mark.asyncio
async def test_admin_lists_and_requeues_failed_notification_idempotently() -> None:
    action_token = f"RESEND-{uuid4().hex}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        list_path = "/api/v1/notifications"
        denied = await call(
            client,
            "GET",
            list_path,
            "test-user-01",
            params={"status": "FAILED"},
        )
        assert denied.status_code == 403

        listed = await call(
            client,
            "GET",
            list_path,
            "test-user-05",
            params={"status": "FAILED"},
        )
        assert listed.status_code == 200, listed.text
        assert [item["notification_id"] for item in listed.json()["data"]["items"]] == [99703]

        dispatch_path = "/api/v1/notifications/dispatch-due"
        dispatch_denied = await call(
            client,
            "POST",
            dispatch_path,
            "test-user-01",
            json={"batch_size": 10},
        )
        assert dispatch_denied.status_code == 403

        resend_path = "/api/v1/notifications/99703/resend"
        payload = {
            "reason": "管理员确认接收账号已恢复",
            "action_token": action_token,
        }
        resent = await call(
            client,
            "POST",
            resend_path,
            "test-user-05",
            json=payload,
        )
        assert resent.status_code == 200, resent.text
        assert resent.json()["data"] == {
            "notification_id": 99703,
            "status": "PENDING",
            "retry_count": 0,
            "next_retry_at": None,
        }

        duplicate = await call(
            client,
            "POST",
            resend_path,
            "test-user-05",
            json=payload,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "DUPLICATE_OPERATION"

        sent_resend_path = "/api/v1/notifications/99702/resend"
        invalid = await call(
            client,
            "POST",
            sent_resend_path,
            "test-user-05",
            json={
                "reason": "不应补发已成功通知",
                "action_token": f"RESEND-{uuid4().hex}",
            },
        )
        assert invalid.status_code == 409
        assert invalid.json()["code"] == "INVALID_NOTIFICATION_STATUS"

    async with async_session_factory() as session:
        notification = await session.get(NotificationOutbox, 99703)
        log = await session.scalar(
            select(PurchaseOperationLog).where(PurchaseOperationLog.action_token == action_token)
        )
        assert notification is not None
        assert log is not None
        assert notification.status == "PENDING"
        assert "补发前错误" in notification.last_error
        assert log.action_type == "RESEND_NOTIFICATION"
