from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationOutbox
from app.models.procurement import PurchaseOperationLog


class NotificationRepository:
    async def claim_due(
        self,
        session: AsyncSession,
        now: datetime,
        batch_size: int,
        max_retries: int,
    ) -> list[NotificationOutbox]:
        return list(
            (
                await session.scalars(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.retry_count < max_retries,
                        or_(
                            NotificationOutbox.status == "PENDING",
                            (
                                (NotificationOutbox.status == "FAILED")
                                & (NotificationOutbox.next_retry_at.is_not(None))
                                & (NotificationOutbox.next_retry_at <= now)
                            ),
                        ),
                    )
                    .order_by(
                        NotificationOutbox.created_at,
                        NotificationOutbox.notification_id,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )

    async def get(
        self,
        session: AsyncSession,
        notification_id: int,
        *,
        for_update: bool = False,
    ) -> NotificationOutbox | None:
        statement = select(NotificationOutbox).where(
            NotificationOutbox.notification_id == notification_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list(
        self,
        session: AsyncSession,
        *,
        status: str | None,
        request_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[NotificationOutbox], int]:
        conditions = []
        if status:
            conditions.append(NotificationOutbox.status == status)
        if request_id is not None:
            conditions.append(NotificationOutbox.request_id == request_id)
        total = int(
            await session.scalar(
                select(func.count()).select_from(NotificationOutbox).where(*conditions)
            )
            or 0
        )
        notifications = list(
            (
                await session.scalars(
                    select(NotificationOutbox)
                    .where(*conditions)
                    .order_by(
                        NotificationOutbox.created_at.desc(),
                        NotificationOutbox.notification_id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return notifications, total

    async def action_token_exists(
        self,
        session: AsyncSession,
        action_token: str,
    ) -> bool:
        return bool(
            await session.scalar(
                select(func.count())
                .select_from(PurchaseOperationLog)
                .where(PurchaseOperationLog.action_token == action_token)
            )
        )
