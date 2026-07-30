from dataclasses import dataclass
from typing import Protocol

from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.models.notification import NotificationOutbox


class NotificationDeliveryError(Exception):
    pass


class NotificationSender(Protocol):
    async def send(self, notification: NotificationOutbox) -> None: ...


@dataclass
class HttpNotificationSender:
    settings: Settings

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send(self, notification: NotificationOutbox) -> None:
        if not self.settings.notification_gateway_url:
            raise NotificationDeliveryError("通知发送网关未配置")

        headers = {
            "Idempotency-Key": notification.dedup_key,
            "X-Notification-Id": str(notification.notification_id),
        }
        if self.settings.notification_gateway_token:
            headers["Authorization"] = f"Bearer {self.settings.notification_gateway_token}"
        body = {
            "notification_id": notification.notification_id,
            "dedup_key": notification.dedup_key,
            "event_type": notification.event_type,
            "platform_type": notification.platform_type,
            "receiver_platform_user_id": (notification.receiver_platform_user_id_snapshot),
            "payload": notification.payload,
        }
        try:
            async with AsyncClient(
                timeout=self.settings.notification_request_timeout_seconds
            ) as client:
                response = await client.post(
                    self.settings.notification_gateway_url,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
        except Exception as exc:
            raise NotificationDeliveryError(f"通知网关调用失败：{type(exc).__name__}") from exc
