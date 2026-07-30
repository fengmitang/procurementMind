from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.models.identity import Employee
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    WarehouseReceipt,
)


class PurchaseRecordRepository:
    @staticmethod
    def _visibility_condition(current_user: CurrentUser):
        if current_user.has_any_role(RoleCode.ADMIN.value):
            return None
        if current_user.has_any_role(RoleCode.BUILDING_MANAGER.value):
            return PurchaseRequest.building_id.in_(current_user.building_ids)
        return or_(
            PurchaseRequest.applicant_employee_id == current_user.employee_id,
            PurchaseRequest.current_handler_employee_id == current_user.employee_id,
            exists().where(
                PurchaseOperationLog.request_id == PurchaseRequest.request_id,
                PurchaseOperationLog.operator_employee_id == current_user.employee_id,
            ),
        )

    async def list_records(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        requirement_no: str | None,
        supplier_id: int | None,
        status: str | None,
        device_name: str | None,
        brand: str | None,
        model: str | None,
        created_from: date | None,
        created_to: date | None,
        page: int,
        page_size: int,
    ) -> tuple[
        list[
            tuple[
                PurchaseRequest,
                PurchaseExecution | None,
                datetime | None,
                datetime | None,
            ]
        ],
        int,
    ]:
        conditions = []
        visibility = self._visibility_condition(current_user)
        if visibility is not None:
            conditions.append(visibility)
        if requirement_no:
            conditions.append(PurchaseRequest.request_no.like(f"%{requirement_no}%"))
        if supplier_id is not None:
            conditions.append(PurchaseExecution.supplier_id == supplier_id)
        if status:
            conditions.append(PurchaseRequest.status == status)
        if device_name:
            conditions.append(PurchaseRequest.device_name.like(f"%{device_name}%"))
        if brand:
            conditions.append(PurchaseRequest.brand.like(f"%{brand}%"))
        if model:
            conditions.append(PurchaseRequest.model.like(f"%{model}%"))
        if created_from:
            conditions.append(
                PurchaseRequest.created_at >= datetime.combine(created_from, time.min)
            )
        if created_to:
            conditions.append(
                PurchaseRequest.created_at
                < datetime.combine(created_to + timedelta(days=1), time.min)
            )

        reviewed_at = (
            select(func.max(PurchaseReview.reviewed_at))
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        received_at = (
            select(func.max(WarehouseReceipt.received_at))
            .where(WarehouseReceipt.request_id == PurchaseRequest.request_id)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        base = (
            select(PurchaseRequest, PurchaseExecution, reviewed_at, received_at)
            .outerjoin(
                PurchaseExecution,
                PurchaseExecution.request_id == PurchaseRequest.request_id,
            )
            .where(*conditions)
        )
        total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        result = await session.execute(
            base.order_by(
                PurchaseRequest.created_at.desc(),
                PurchaseRequest.request_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.tuples()), total

    async def timeline(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> list[tuple[PurchaseOperationLog, str | None, str | None]]:
        assigned_employee = aliased(Employee)
        result = await session.execute(
            select(
                PurchaseOperationLog,
                assigned_employee.name,
                assigned_employee.mobile,
            )
            .outerjoin(
                assigned_employee,
                assigned_employee.employee_id == PurchaseOperationLog.assigned_to_employee_id,
            )
            .where(
                PurchaseOperationLog.request_id == request_id,
                or_(
                    PurchaseOperationLog.action_type == "CREATE_DRAFT",
                    PurchaseOperationLog.from_status != PurchaseOperationLog.to_status,
                ),
            )
            .order_by(
                PurchaseOperationLog.operated_at,
                PurchaseOperationLog.log_id,
            )
        )
        return list(result.tuples())

    async def get_timeline_log(
        self,
        session: AsyncSession,
        request_id: int,
        log_id: int,
    ) -> tuple[PurchaseOperationLog, str | None, str | None] | None:
        assigned_employee = aliased(Employee)
        result = await session.execute(
            select(
                PurchaseOperationLog,
                assigned_employee.name,
                assigned_employee.mobile,
            )
            .outerjoin(
                assigned_employee,
                assigned_employee.employee_id == PurchaseOperationLog.assigned_to_employee_id,
            )
            .where(
                PurchaseOperationLog.request_id == request_id,
                PurchaseOperationLog.log_id == log_id,
            )
        )
        return result.tuples().one_or_none()
