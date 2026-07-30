from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.notifications import (
    DispatchNotificationsData,
    DispatchNotificationsRequest,
    NotificationListData,
    ResendNotificationData,
    ResendNotificationRequest,
)
from app.services.notifications import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=ApiResponse[NotificationListData])
async def list_notifications(
    current_user: CurrentUserDependency,
    session: DbSession,
    status: str | None = Query(default=None),
    request_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[NotificationListData]:
    data = await NotificationService().list_notifications(
        session,
        current_user,
        status=status,
        request_id=request_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.post(
    "/dispatch-due",
    response_model=ApiResponse[DispatchNotificationsData],
)
async def dispatch_due_notifications(
    payload: DispatchNotificationsRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[DispatchNotificationsData]:
    data = await NotificationService().dispatch_as_admin(
        session,
        current_user,
        payload.batch_size,
    )
    return ApiResponse(data=data)


@router.post(
    "/{notification_id}/resend",
    response_model=ApiResponse[ResendNotificationData],
)
async def resend_notification(
    notification_id: int,
    payload: ResendNotificationRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[ResendNotificationData]:
    data = await NotificationService().resend(
        session,
        current_user,
        notification_id,
        payload.reason,
        payload.action_token,
    )
    return ApiResponse(data=data)
