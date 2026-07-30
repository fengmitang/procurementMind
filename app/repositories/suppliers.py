from datetime import datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    Supplier,
    SupplierBlacklist,
)


def effective_blacklist_condition(now: datetime):
    return (SupplierBlacklist.status == "ACTIVE") & (
        (SupplierBlacklist.duration_type == "PERMANENT")
        | ((SupplierBlacklist.duration_type == "LIMITED") & (SupplierBlacklist.end_at > now))
    )


class SupplierRepository:
    async def search(
        self,
        session: AsyncSession,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Supplier], int]:
        pattern = f"%{keyword}%"
        condition = Supplier.status.is_(True) & (
            Supplier.supplier_name.like(pattern) | Supplier.unified_social_credit_code.like(pattern)
        )
        total = int(
            await session.scalar(select(func.count()).select_from(Supplier).where(condition)) or 0
        )
        suppliers = list(
            (
                await session.scalars(
                    select(Supplier)
                    .where(condition)
                    .order_by(Supplier.supplier_name, Supplier.supplier_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return suppliers, total

    async def get(self, session: AsyncSession, supplier_id: int) -> Supplier | None:
        return await session.get(Supplier, supplier_id)

    async def find_conflict(
        self,
        session: AsyncSession,
        supplier_name: str,
        credit_code: str | None,
    ) -> Supplier | None:
        conditions = [Supplier.supplier_name == supplier_name]
        if credit_code:
            conditions.append(Supplier.unified_social_credit_code == credit_code)
        return await session.scalar(select(Supplier).where(or_(*conditions)).limit(1))

    async def blacklist_summary(
        self,
        session: AsyncSession,
        supplier_id: int,
        now: datetime,
    ) -> tuple[str, int]:
        history_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SupplierBlacklist)
                .where(SupplierBlacklist.supplier_id == supplier_id)
            )
            or 0
        )
        active = bool(
            await session.scalar(
                select(
                    exists().where(
                        SupplierBlacklist.supplier_id == supplier_id,
                        effective_blacklist_condition(now),
                    )
                )
            )
        )
        if active:
            return "BLACKLISTED", history_count
        return ("HISTORY" if history_count else "NORMAL"), history_count

    async def get_blacklist(
        self,
        session: AsyncSession,
        blacklist_id: int,
    ) -> SupplierBlacklist | None:
        return await session.get(SupplierBlacklist, blacklist_id)

    async def has_effective_blacklist(
        self,
        session: AsyncSession,
        supplier_id: int,
        now: datetime,
    ) -> bool:
        return bool(
            await session.scalar(
                select(
                    exists().where(
                        SupplierBlacklist.supplier_id == supplier_id,
                        effective_blacklist_condition(now),
                    )
                )
            )
        )

    async def action_token_exists(
        self,
        session: AsyncSession,
        action_token: str,
    ) -> bool:
        return bool(
            await session.scalar(
                select(exists().where(PurchaseOperationLog.action_token == action_token))
            )
        )

    async def get_completed_request_supplier(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> tuple[PurchaseRequest, PurchaseExecution] | None:
        row = (
            await session.execute(
                select(PurchaseRequest, PurchaseExecution)
                .join(
                    PurchaseExecution,
                    PurchaseExecution.request_id == PurchaseRequest.request_id,
                )
                .where(
                    PurchaseRequest.request_id == request_id,
                    PurchaseRequest.status == "COMPLETED",
                )
            )
        ).one_or_none()
        if row is None:
            return None
        request, execution = row
        return request, execution
