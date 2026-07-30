from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.procurement import (
    PurchaseExecution,
    PurchaseRequest,
    Supplier,
)
from app.repositories.suppliers import SupplierRepository


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
