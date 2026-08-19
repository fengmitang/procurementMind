from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.procurement import (
    PurchaseExecution,
    PurchaseRequest,
    PurchaseReview,
    Supplier,
    SupplierBlacklist,
    WarehouseReceipt,
)
from app.repositories.suppliers import SupplierRepository, effective_blacklist_condition


class RecommendationRepository:
    def __init__(self, supplier_repository: SupplierRepository | None = None) -> None:
        self.suppliers = supplier_repository or SupplierRepository()

    @staticmethod
    def _valid_history():
        return (
            PurchaseExecution.request_id == PurchaseRequest.request_id,
            PurchaseRequest.status.in_(["PENDING_WAREHOUSE", "COMPLETED"]),
            ~PurchaseRequest.request_no.like("TEST-%"),
        )

    async def products(
        self,
        session: AsyncSession,
        *,
        device_profession: str | None,
        device_name: str,
        keyword: str | None,
        limit: int,
    ) -> list[tuple[str | None, str | None, int, datetime]]:
        statement = (
            select(
                PurchaseRequest.brand,
                PurchaseRequest.model,
                func.count().label("historical_count"),
                func.max(PurchaseExecution.purchased_at).label("last_purchased_at"),
            )
            .join(
                PurchaseExecution,
                PurchaseExecution.request_id == PurchaseRequest.request_id,
            )
            .where(
                *self._valid_history(),
                PurchaseRequest.device_name.like(f"%{device_name}%"),
            )
        )
        if device_profession:
            statement = statement.where(PurchaseRequest.device_profession == device_profession)
        if keyword:
            statement = statement.where(
                PurchaseRequest.brand.like(f"%{keyword}%")
                | PurchaseRequest.model.like(f"%{keyword}%")
            )
        result = await session.execute(
            statement.group_by(PurchaseRequest.brand, PurchaseRequest.model)
            .order_by(desc("historical_count"), desc("last_purchased_at"))
            .limit(limit)
        )
        return list(result.tuples())

    async def similar_history(
        self,
        session: AsyncSession,
        current_request: PurchaseRequest,
        limit: int,
    ) -> list[tuple[PurchaseRequest, PurchaseExecution]]:
        result = await session.execute(
            select(PurchaseRequest, PurchaseExecution)
            .join(
                PurchaseExecution,
                PurchaseExecution.request_id == PurchaseRequest.request_id,
            )
            .where(
                *self._valid_history(),
                PurchaseRequest.request_id != current_request.request_id,
                PurchaseRequest.device_name.like(f"%{current_request.device_name or ''}%"),
            )
            .order_by(PurchaseExecution.purchased_at.desc())
            .limit(limit)
        )
        return [(request, execution) for request, execution in result.tuples()]

    async def supplier_history(
        self,
        session: AsyncSession,
        current_request: PurchaseRequest,
        limit: int,
    ) -> list[tuple[Supplier, int, datetime]]:
        result = await session.execute(
            select(
                Supplier,
                func.count(PurchaseExecution.execution_id).label("purchase_count"),
                func.max(PurchaseExecution.purchased_at).label("last_purchase_at"),
            )
            .join(PurchaseExecution, PurchaseExecution.supplier_id == Supplier.supplier_id)
            .join(PurchaseRequest, PurchaseRequest.request_id == PurchaseExecution.request_id)
            .where(
                *self._valid_history(),
                Supplier.status.is_(True),
                PurchaseRequest.device_profession == current_request.device_profession,
            )
            .group_by(Supplier.supplier_id)
            .order_by(desc("purchase_count"), desc("last_purchase_at"))
            .limit(limit * 3)
        )
        return [
            (supplier, purchase_count, last_purchase_at)
            for supplier, purchase_count, last_purchase_at in result
        ]

    async def product_evidence(
        self,
        session: AsyncSession,
        *,
        device_profession: str | None,
        device_names: list[str],
        purchased_from: datetime | None,
        purchased_to: datetime | None,
        limit: int,
    ) -> list[tuple[PurchaseRequest, PurchaseExecution]]:
        statement = select(PurchaseRequest, PurchaseExecution).join(
            PurchaseExecution, PurchaseExecution.request_id == PurchaseRequest.request_id
        ).where(*self._valid_history())
        statement = self._apply_device_filters(statement, device_profession, device_names)
        statement = self._apply_time_filters(
            statement, PurchaseExecution.purchased_at, purchased_from, purchased_to
        )
        result = await session.execute(
            statement.order_by(PurchaseExecution.purchased_at.desc()).limit(limit)
        )
        return list(result.tuples())

    async def supplier_evidence(
        self,
        session: AsyncSession,
        *,
        device_profession: str | None,
        device_names: list[str],
        brand: str | None,
        model: str | None,
        purchased_from: datetime | None,
        purchased_to: datetime | None,
        building_ids: set[int] | None,
        limit: int,
    ) -> list[tuple[PurchaseRequest, PurchaseExecution]]:
        statement = select(PurchaseRequest, PurchaseExecution).join(
            PurchaseExecution, PurchaseExecution.request_id == PurchaseRequest.request_id
        ).where(*self._valid_history())
        statement = self._apply_device_filters(statement, device_profession, device_names)
        if brand:
            statement = statement.where(PurchaseRequest.brand == brand)
        if model:
            statement = statement.where(PurchaseRequest.model == model)
        if building_ids is not None:
            statement = statement.where(PurchaseRequest.building_id.in_(building_ids))
        statement = self._apply_time_filters(
            statement, PurchaseExecution.purchased_at, purchased_from, purchased_to
        )
        result = await session.execute(
            statement.order_by(PurchaseExecution.purchased_at.desc()).limit(limit)
        )
        return list(result.tuples())

    async def supplier_contract_evidence(
        self,
        session: AsyncSession,
        *,
        supplier_id: int | None,
        supplier_name: str | None,
        purchased_from: datetime | None,
        purchased_to: datetime | None,
        limit: int,
    ) -> list[tuple[PurchaseExecution]]:
        statement = select(PurchaseExecution).join(
            PurchaseRequest, PurchaseRequest.request_id == PurchaseExecution.request_id
        ).where(*self._valid_history())
        if supplier_id is not None:
            statement = statement.where(PurchaseExecution.supplier_id == supplier_id)
        elif supplier_name:
            statement = statement.where(PurchaseExecution.supplier_name_snapshot == supplier_name)
        statement = self._apply_time_filters(
            statement, PurchaseExecution.purchased_at, purchased_from, purchased_to
        )
        result = await session.execute(
            statement.order_by(PurchaseExecution.purchased_at.desc()).limit(limit)
        )
        return [(execution,) for execution in result.scalars()]

    async def matching_suppliers(
        self, session: AsyncSession, supplier_name: str
    ) -> list[Supplier]:
        return list(
            (
                await session.scalars(
                    select(Supplier)
                    .where(Supplier.supplier_name == supplier_name)
                    .order_by(Supplier.supplier_id)
                )
            ).all()
        )

    async def suppliers_by_ids(
        self, session: AsyncSession, supplier_ids: set[int]
    ) -> dict[int, Supplier]:
        if not supplier_ids:
            return {}
        suppliers = (
            await session.scalars(select(Supplier).where(Supplier.supplier_id.in_(supplier_ids)))
        ).all()
        return {supplier.supplier_id: supplier for supplier in suppliers}

    async def warehouse_evidence(
        self,
        session: AsyncSession,
        *,
        device_profession: str | None,
        device_names: list[str],
        received_from: datetime | None,
        received_to: datetime | None,
        limit: int,
    ) -> list[tuple[PurchaseRequest, WarehouseReceipt]]:
        statement = select(PurchaseRequest, WarehouseReceipt).join(
            WarehouseReceipt, WarehouseReceipt.request_id == PurchaseRequest.request_id
        ).where(~PurchaseRequest.request_no.like("TEST-%"))
        statement = self._apply_device_filters(statement, device_profession, device_names)
        statement = self._apply_time_filters(
            statement, WarehouseReceipt.received_at, received_from, received_to
        )
        result = await session.execute(
            statement.order_by(WarehouseReceipt.received_at.desc()).limit(limit)
        )
        return list(result.tuples())

    async def latest_completed_reviews(
        self, session: AsyncSession, request_ids: set[int]
    ) -> dict[int, PurchaseReview]:
        if not request_ids:
            return {}
        latest = (
            select(
                PurchaseReview.request_id,
                func.max(PurchaseReview.review_round).label("review_round"),
            )
            .where(
                PurchaseReview.request_id.in_(request_ids),
                PurchaseReview.review_status == "COMPLETED",
            )
            .group_by(PurchaseReview.request_id)
            .subquery()
        )
        reviews = (
            await session.scalars(
                select(PurchaseReview).join(
                    latest,
                    (PurchaseReview.request_id == latest.c.request_id)
                    & (PurchaseReview.review_round == latest.c.review_round),
                )
            )
        ).all()
        return {review.request_id: review for review in reviews}

    async def supplier_blacklist_summaries(
        self, session: AsyncSession, supplier_ids: set[int], now: datetime
    ) -> dict[int, tuple[str, int]]:
        if not supplier_ids:
            return {}
        counts = dict(
            (
                await session.execute(
                    select(SupplierBlacklist.supplier_id, func.count())
                    .where(SupplierBlacklist.supplier_id.in_(supplier_ids))
                    .group_by(SupplierBlacklist.supplier_id)
                )
            ).tuples().all()
        )
        active = set(
            (
                await session.scalars(
                    select(SupplierBlacklist.supplier_id)
                    .where(
                        SupplierBlacklist.supplier_id.in_(supplier_ids),
                        effective_blacklist_condition(now),
                    )
                    .distinct()
                )
            ).all()
        )
        return {
            supplier_id: (
                "BLACKLISTED"
                if supplier_id in active
                else "HISTORY"
                if counts.get(supplier_id, 0)
                else "NORMAL",
                int(counts.get(supplier_id, 0)),
            )
            for supplier_id in supplier_ids
        }

    @staticmethod
    def _apply_device_filters(statement, device_profession: str | None, device_names: list[str]):
        conditions = []
        if device_profession:
            conditions.append(PurchaseRequest.device_profession == device_profession)
        if device_names:
            conditions.append(PurchaseRequest.device_name.in_(device_names))
        return statement.where(*conditions) if conditions else statement

    @staticmethod
    def _apply_time_filters(statement, field, start: datetime | None, end: datetime | None):
        if start:
            statement = statement.where(field >= start)
        if end:
            statement = statement.where(field <= end)
        return statement
