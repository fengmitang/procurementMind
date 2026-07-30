from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import PurchaseStatus, RoleCode
from app.domain.identity import CurrentUser
from app.repositories.procurement import ProcurementRepository
from app.repositories.records import PurchaseRecordRepository
from app.schemas.records import (
    PurchaseRecordItem,
    PurchaseRecordListData,
    TimelineContactData,
    TimelineData,
    TimelineItem,
)
from app.services.privacy import mask_mobile


class PurchaseRecordService:
    def __init__(
        self,
        repository: PurchaseRecordRepository | None = None,
        procurement_repository: ProcurementRepository | None = None,
    ) -> None:
        self.repository = repository or PurchaseRecordRepository()
        self.procurement = procurement_repository or ProcurementRepository()

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
    ) -> PurchaseRecordListData:
        normalized_status = status.upper() if status else None
        if normalized_status and normalized_status not in {item.value for item in PurchaseStatus}:
            raise AppError("VALIDATION_ERROR", "采购状态筛选值无效", 422)
        if created_from and created_to and created_from > created_to:
            raise AppError(
                "VALIDATION_ERROR",
                "created_from 不能晚于 created_to",
                422,
            )
        rows, total = await self.repository.list_records(
            session,
            current_user,
            requirement_no=requirement_no,
            supplier_id=supplier_id,
            status=normalized_status,
            device_name=device_name,
            brand=brand,
            model=model,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
        )
        return PurchaseRecordListData(
            items=[
                PurchaseRecordItem(
                    requirement_id=request.request_id,
                    requirement_no=request.request_no,
                    device_name=request.device_name,
                    brand=request.brand,
                    model=request.model,
                    quantity=request.quantity,
                    unit=request.unit,
                    status=request.status,
                    supplier_id=execution.supplier_id if execution else None,
                    supplier_name=(execution.supplier_name_snapshot if execution else None),
                    actual_total_price=(execution.actual_total_price if execution else None),
                    purchased_at=execution.purchased_at if execution else None,
                    created_at=request.created_at,
                    submitted_at=request.submitted_at,
                    reviewed_at=reviewed_at,
                    received_at=received_at,
                    completed_at=request.completed_at,
                )
                for request, execution, reviewed_at, received_at in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def timeline(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
    ) -> TimelineData:
        await self._require_visible_request(session, current_user, request_id)
        rows = await self.repository.timeline(session, request_id)
        return TimelineData(
            items=[
                TimelineItem(
                    log_id=log.log_id,
                    action_type=log.action_type,
                    operator_name=log.operator_name_snapshot,
                    operator_role_name=log.operator_role_name_snapshot,
                    operator_mobile_masked=mask_mobile(log.operator_mobile_snapshot),
                    from_status=log.from_status,
                    to_status=log.to_status,
                    assigned_to_employee_id=log.assigned_to_employee_id,
                    assigned_to_name=assigned_to_name,
                    assigned_to_mobile_masked=mask_mobile(assigned_to_mobile),
                    operation_summary=log.operation_summary,
                    operated_at=log.operated_at,
                )
                for log, assigned_to_name, assigned_to_mobile in rows
            ]
        )

    async def timeline_contact(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        log_id: int,
        subject: str,
    ) -> TimelineContactData:
        await self._require_visible_request(session, current_user, request_id)
        row = await self.repository.get_timeline_log(session, request_id, log_id)
        if row is None:
            raise AppError("TIMELINE_ITEM_NOT_FOUND", "流程记录不存在", 404)
        log, assigned_to_name, assigned_to_mobile = row
        if subject == "assignee":
            if log.assigned_to_employee_id is None or assigned_to_name is None:
                raise AppError("CONTACT_NOT_FOUND", "该流程记录没有下一处理人", 404)
            return TimelineContactData(
                employee_name=assigned_to_name,
                mobile=assigned_to_mobile,
            )
        return TimelineContactData(
            employee_name=log.operator_name_snapshot,
            mobile=log.operator_mobile_snapshot,
        )

    async def _require_visible_request(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
    ) -> None:
        request = await self.procurement.get_request(session, request_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)
        visible = await self.procurement.can_view_request(
            session,
            request,
            current_user.employee_id,
            current_user.has_any_role(RoleCode.ADMIN.value),
            current_user.building_ids,
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value),
        )
        if not visible:
            raise AppError("PERMISSION_DENIED", "无权查看该采购流程记录", 403)
