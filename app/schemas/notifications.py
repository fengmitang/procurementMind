from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    notification_id: int
    request_id: int
    event_type: str
    receiver_employee_id: int
    platform_type: str
    receiver_platform_user_id_snapshot: str
    dedup_key: str
    payload: dict[str, Any]
    status: str
    retry_count: int
    next_retry_at: datetime | None
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    updated_at: datetime


class NotificationListData(BaseModel):
    items: list[NotificationItem]
    page: int
    page_size: int
    total: int


class DispatchNotificationsRequest(BaseModel):
    batch_size: int = Field(default=50, ge=1, le=200)


class DispatchNotificationsData(BaseModel):
    claimed: int
    sent: int
    failed: int
    exhausted: int


class ResendNotificationRequest(BaseModel):
    reason: str = Field(min_length=1)
    action_token: str = Field(min_length=8, max_length=64)


class ResendNotificationData(BaseModel):
    notification_id: int
    status: str
    retry_count: int
    next_retry_at: datetime | None
