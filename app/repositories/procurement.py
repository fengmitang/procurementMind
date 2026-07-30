from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Building, Employee, EmployeeExternalIdentity
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    Supplier,
    WarehouseReceipt,
)


class ProcurementRepository:
    async def get_request(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseRequest | None:
        return await session.get(PurchaseRequest, request_id)

    async def get_supplier(
        self,
        session: AsyncSession,
        supplier_id: int,
    ) -> Supplier | None:
        return await session.get(Supplier, supplier_id)

    async def get_execution(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseExecution | None:
        return await session.scalar(
            select(PurchaseExecution).where(PurchaseExecution.request_id == request_id)
        )

    async def get_receipt(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> WarehouseReceipt | None:
        return await session.scalar(
            select(WarehouseReceipt).where(WarehouseReceipt.request_id == request_id)
        )

    async def get_active_review(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseReview | None:
        return await session.scalar(
            select(PurchaseReview)
            .where(
                PurchaseReview.request_id == request_id,
                PurchaseReview.review_status == "DRAFT",
            )
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
        )

    async def get_latest_review(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseReview | None:
        return await session.scalar(
            select(PurchaseReview)
            .where(PurchaseReview.request_id == request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
        )

    async def next_review_round(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> int:
        latest = await session.scalar(
            select(func.max(PurchaseReview.review_round)).where(
                PurchaseReview.request_id == request_id
            )
        )
        return int(latest or 0) + 1

    async def bump_version(
        self,
        session: AsyncSession,
        *,
        request_id: int,
        expected_version: int,
        allowed_statuses: Sequence[str],
        values: dict | None = None,
    ) -> bool:
        update_values = {
            "version": PurchaseRequest.version + 1,
            "updated_at": datetime.now(),
            **(values or {}),
        }
        result = await session.execute(
            update(PurchaseRequest)
            .where(
                PurchaseRequest.request_id == request_id,
                PurchaseRequest.version == expected_version,
                PurchaseRequest.status.in_(allowed_statuses),
            )
            .values(**update_values)
        )
        return result.rowcount == 1

    async def get_employee_handler(
        self,
        session: AsyncSession,
        employee_id: int | None,
    ) -> tuple[int, str] | None:
        if employee_id is None:
            return None
        row = (
            await session.execute(
                select(Employee.employee_id, Employee.name).where(
                    Employee.employee_id == employee_id
                )
            )
        ).one_or_none()
        return tuple(row) if row else None

    async def get_platform_identities(
        self,
        session: AsyncSession,
        employee_id: int,
    ) -> list[tuple[str, str]]:
        result = await session.execute(
            select(
                EmployeeExternalIdentity.platform_type,
                EmployeeExternalIdentity.platform_user_id,
            ).where(
                EmployeeExternalIdentity.employee_id == employee_id,
                EmployeeExternalIdentity.status.is_(True),
            )
        )
        return list(result.tuples())

    async def can_view_request(
        self,
        session: AsyncSession,
        request: PurchaseRequest,
        employee_id: int,
        is_admin: bool,
        building_ids: frozenset[int],
        is_building_manager: bool,
    ) -> bool:
        if (
            is_admin
            or request.applicant_employee_id == employee_id
            or request.current_handler_employee_id == employee_id
            or (is_building_manager and request.building_id in building_ids)
        ):
            return True
        return bool(
            await session.scalar(
                select(
                    exists().where(
                        PurchaseOperationLog.request_id == request.request_id,
                        PurchaseOperationLog.operator_employee_id == employee_id,
                    )
                )
            )
        )

    async def get_detail_rows(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> tuple[
        Building | None,
        Employee | None,
        list[PurchaseReview],
        PurchaseExecution | None,
        WarehouseReceipt | None,
    ]:
        building = await session.get(
            Building,
            (await self.get_request(session, request_id)).building_id,
        )
        request = await self.get_request(session, request_id)
        handler = (
            await session.get(Employee, request.current_handler_employee_id)
            if request and request.current_handler_employee_id
            else None
        )
        reviews = list(
            (
                await session.scalars(
                    select(PurchaseReview)
                    .where(PurchaseReview.request_id == request_id)
                    .order_by(PurchaseReview.review_round)
                )
            ).all()
        )
        return (
            building,
            handler,
            reviews,
            await self.get_execution(session, request_id),
            await self.get_receipt(session, request_id),
        )

    def list_statement(
        self,
        *,
        employee_id: int,
        view: str,
        status: str | None,
        building_ids: frozenset[int] = frozenset(),
    ) -> Select:
        statement = select(PurchaseRequest)
        if view == "CREATED_BY_ME":
            statement = statement.where(PurchaseRequest.applicant_employee_id == employee_id)
        elif view == "PENDING_FOR_ME":
            statement = statement.where(PurchaseRequest.current_handler_employee_id == employee_id)
        elif view == "BUILDING_SCOPE":
            statement = statement.where(PurchaseRequest.building_id.in_(building_ids))
        else:
            statement = statement.where(
                or_(
                    PurchaseRequest.applicant_employee_id == employee_id,
                    exists().where(
                        PurchaseOperationLog.request_id == PurchaseRequest.request_id,
                        PurchaseOperationLog.operator_employee_id == employee_id,
                    ),
                )
            )
        if status:
            statement = statement.where(PurchaseRequest.status == status)
        return statement

    async def list_requests(
        self,
        session: AsyncSession,
        *,
        employee_id: int,
        view: str,
        status: str | None,
        building_ids: frozenset[int] = frozenset(),
        page: int,
        page_size: int,
    ) -> tuple[list[PurchaseRequest], int]:
        statement = self.list_statement(
            employee_id=employee_id,
            view=view,
            status=status,
            building_ids=building_ids,
        )
        total = int(
            await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            (
                await session.scalars(
                    statement.order_by(PurchaseRequest.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, total
