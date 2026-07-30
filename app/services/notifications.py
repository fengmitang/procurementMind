from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser, UserRole
from app.integrations.notification_sender import (
    HttpNotificationSender,
    NotificationSender,
)
from app.models.notification import NotificationOutbox
from app.models.procurement import PurchaseOperationLog, PurchaseRequest
from app.repositories.notifications import NotificationRepository
from app.schemas.notifications import (
    DispatchNotificationsData,
    NotificationItem,
    NotificationListData,
    ResendNotificationData,
)
from app.services.permissions import require_any_role


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository | None = None,
        sender: NotificationSender | None = None,
    ) -> None:
        self.repository = repository or NotificationRepository()
        self.sender = sender or HttpNotificationSender()
        self.settings = get_settings()

    async def dispatch_due(
        self,
        session: AsyncSession,
        *,
        batch_size: int | None = None,
    ) -> DispatchNotificationsData:
        size = batch_size or self.settings.notification_worker_batch_size
        now = self._now()
        notifications = await self.repository.claim_due(
            session,
            now,
            size,
            self.settings.notification_max_retries,
        )
        sent = 0
        failed = 0
        exhausted = 0
        for notification in notifications:
            try:
                await self.sender.send(notification)
            except Exception as exc:
                failed += 1
                notification.retry_count += 1
                notification.status = "FAILED"
                notification.sent_at = None
                notification.last_error = self._safe_error(exc)
                if notification.retry_count >= self.settings.notification_max_retries:
                    notification.next_retry_at = None
                    exhausted += 1
                else:
                    notification.next_retry_at = now + timedelta(
                        seconds=self._retry_delay(notification.retry_count)
                    )
            else:
                sent += 1
                notification.status = "SENT"
                notification.sent_at = now
                notification.next_retry_at = None
                notification.last_error = None
            notification.updated_at = now
        await session.flush()
        return DispatchNotificationsData(
            claimed=len(notifications),
            sent=sent,
            failed=failed,
            exhausted=exhausted,
        )

    async def dispatch_as_admin(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        batch_size: int,
    ) -> DispatchNotificationsData:
        require_any_role(current_user, RoleCode.ADMIN.value)
        return await self.dispatch_due(session, batch_size=batch_size)

    async def list_notifications(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        status: str | None,
        request_id: int | None,
        page: int,
        page_size: int,
    ) -> NotificationListData:
        require_any_role(current_user, RoleCode.ADMIN.value)
        normalized_status = status.upper() if status else None
        if normalized_status and normalized_status not in {
            "PENDING",
            "SENT",
            "FAILED",
        }:
            raise AppError("VALIDATION_ERROR", "通知状态筛选值无效", 422)
        notifications, total = await self.repository.list(
            session,
            status=normalized_status,
            request_id=request_id,
            page=page,
            page_size=page_size,
        )
        return NotificationListData(
            items=[self._item(notification) for notification in notifications],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def resend(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        notification_id: int,
        reason: str,
        action_token: str,
    ) -> ResendNotificationData:
        require_any_role(current_user, RoleCode.ADMIN.value)
        actor_role = self._admin_role(current_user)
        if await self.repository.action_token_exists(session, action_token):
            raise AppError("DUPLICATE_OPERATION", "该补发操作已经执行", 409)
        notification = await self.repository.get(
            session,
            notification_id,
            for_update=True,
        )
        if notification is None:
            raise AppError("NOTIFICATION_NOT_FOUND", "通知记录不存在", 404)
        if notification.status != "FAILED":
            raise AppError(
                "INVALID_NOTIFICATION_STATUS",
                "只有发送失败的通知可以人工补发",
                409,
            )
        request = await session.get(PurchaseRequest, notification.request_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "关联采购申请不存在", 404)

        previous_error = notification.last_error
        notification.status = "PENDING"
        notification.retry_count = 0
        notification.next_retry_at = None
        notification.last_error = (
            f"人工补发已入队：{reason}"
            + (f"；补发前错误：{previous_error}" if previous_error else "")
        )[:2000]
        notification.updated_at = self._now()
        session.add(
            PurchaseOperationLog(
                request_id=request.request_id,
                operator_employee_id=current_user.employee_id,
                operator_platform_type_snapshot=current_user.platform_type,
                operator_platform_user_id_snapshot=current_user.platform_user_id,
                operator_name_snapshot=current_user.name,
                operator_mobile_snapshot=current_user.mobile,
                operator_role_id_snapshot=actor_role.role_id,
                operator_role_name_snapshot=actor_role.role_name,
                assigned_to_employee_id=None,
                action_token=action_token,
                action_type="RESEND_NOTIFICATION",
                from_status=request.status,
                to_status=request.status,
                operation_summary=(f"人工补发通知 notification_id={notification_id}：{reason}"),
                operated_at=self._now(),
            )
        )
        try:
            await session.flush()
        except IntegrityError as exc:
            if "action_token" in str(exc.orig).lower():
                raise AppError(
                    "DUPLICATE_OPERATION",
                    "该补发操作已经执行",
                    409,
                ) from exc
            raise
        return ResendNotificationData(
            notification_id=notification.notification_id,
            status=notification.status,
            retry_count=notification.retry_count,
            next_retry_at=notification.next_retry_at,
        )

    def _retry_delay(self, retry_count: int) -> int:
        delay = self.settings.notification_retry_base_seconds * (2 ** max(retry_count - 1, 0))
        return min(delay, self.settings.notification_retry_max_seconds)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip() or type(exc).__name__
        return message[:2000]

    @staticmethod
    def _now() -> datetime:
        return datetime.now().replace(microsecond=0)

    @staticmethod
    def _admin_role(current_user: CurrentUser) -> UserRole:
        role = next(
            (item for item in current_user.roles if item.role_code == RoleCode.ADMIN.value),
            None,
        )
        if role is None:
            raise AppError("PERMISSION_DENIED", "当前用户不是管理员", 403)
        return role

    @staticmethod
    def _item(notification: NotificationOutbox) -> NotificationItem:
        return NotificationItem(
            notification_id=notification.notification_id,
            request_id=notification.request_id,
            event_type=notification.event_type,
            receiver_employee_id=notification.receiver_employee_id,
            platform_type=notification.platform_type,
            receiver_platform_user_id_snapshot=(notification.receiver_platform_user_id_snapshot),
            dedup_key=notification.dedup_key,
            payload=notification.payload,
            status=notification.status,
            retry_count=notification.retry_count,
            next_retry_at=notification.next_retry_at,
            last_error=notification.last_error,
            created_at=notification.created_at,
            sent_at=notification.sent_at,
            updated_at=notification.updated_at,
        )
