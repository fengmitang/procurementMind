from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import PurchaseStatus, ReviewStatus, RoleCode
from app.domain.identity import CurrentUser
from app.domain.workflow import WorkflowCommand
from app.models.notification import NotificationOutbox
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    WarehouseReceipt,
)
from app.repositories.procurement import ProcurementRepository
from app.schemas.procurement import (
    ApplicantFields,
    PurchaseFields,
    RequirementDetailData,
    RequirementListData,
    RequirementListItem,
    ReviewFields,
    WarehouseFields,
)
from app.services.permissions import require_any_role, require_building_membership
from app.services.privacy import mask_bank_account, mask_mobile
from app.services.workflow import WorkflowService

APPLICANT_REQUIRED_FIELDS = (
    "device_profession",
    "device_name",
    "quantity",
    "unit",
    "application_reason",
)
REVIEW_REQUIRED_FIELDS = (
    "estimated_unit_price",
    "payment_method",
    "expected_arrival_date",
    "warranty_info",
)


class ProcurementService:
    def __init__(
        self,
        repository: ProcurementRepository | None = None,
        workflow: WorkflowService | None = None,
    ) -> None:
        self.repository = repository or ProcurementRepository()
        self.workflow = workflow or WorkflowService()

    async def create_draft(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        building_id: int,
    ) -> PurchaseRequest:
        require_any_role(current_user, RoleCode.APPLICANT.value)
        require_building_membership(current_user, building_id)
        request = PurchaseRequest(
            request_no=f"PR-{datetime.now():%Y%m%d}-{uuid4().hex[:8].upper()}",
            building_id=building_id,
            applicant_employee_id=current_user.employee_id,
            applicant_platform_type_snapshot=current_user.platform_type,
            applicant_platform_user_id_snapshot=current_user.platform_user_id,
            applicant_name_snapshot=current_user.name,
            applicant_mobile_snapshot=current_user.mobile,
            device_profession=None,
            device_name=None,
            quantity=None,
            unit=None,
            application_reason=None,
            status=PurchaseStatus.DRAFT.value,
            current_handler_employee_id=current_user.employee_id,
            version=0,
        )
        session.add(request)
        await session.flush()
        applicant_role = next(
            role for role in current_user.roles if role.role_code == RoleCode.APPLICANT.value
        )
        session.add(
            PurchaseOperationLog(
                request_id=request.request_id,
                operator_employee_id=current_user.employee_id,
                operator_platform_type_snapshot=current_user.platform_type,
                operator_platform_user_id_snapshot=current_user.platform_user_id,
                operator_name_snapshot=current_user.name,
                operator_mobile_snapshot=current_user.mobile,
                operator_role_id_snapshot=applicant_role.role_id,
                operator_role_name_snapshot=applicant_role.role_name,
                assigned_to_employee_id=current_user.employee_id,
                action_token=None,
                action_type="CREATE_DRAFT",
                from_status=None,
                to_status=PurchaseStatus.DRAFT.value,
                operation_summary="创建采购申请草稿",
                operated_at=datetime.now(),
            )
        )
        await session.flush()
        return request

    async def save_applicant_fields(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        expected_version: int,
        fields: ApplicantFields,
    ) -> tuple[PurchaseRequest, list[str]]:
        request = await self._get_request(session, request_id)
        applicant_can_edit = (
            current_user.has_any_role(RoleCode.APPLICANT.value)
            and request.applicant_employee_id == current_user.employee_id
            and request.status
            in {
                PurchaseStatus.DRAFT.value,
                PurchaseStatus.REJECTED.value,
            }
        )
        manager_can_edit = (
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value)
            and request.current_handler_employee_id == current_user.employee_id
            and request.status == PurchaseStatus.PENDING_REVIEW.value
            and request.building_id in current_user.building_ids
        )
        if not applicant_can_edit and not manager_can_edit:
            raise AppError("INVALID_STATUS", "当前状态不允许修改需求人字段", 409)
        if request.version != expected_version:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请版本已变化", 409)

        values = fields.model_dump(exclude_unset=True)
        allowed_statuses = (
            [PurchaseStatus.PENDING_REVIEW.value]
            if manager_can_edit
            else [
                PurchaseStatus.DRAFT.value,
                PurchaseStatus.REJECTED.value,
            ]
        )
        updated = await self.repository.bump_version(
            session,
            request_id=request_id,
            expected_version=expected_version,
            allowed_statuses=allowed_statuses,
            values=values,
        )
        if not updated:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请已被其他操作更新", 409)
        for key, value in values.items():
            setattr(request, key, value)
        request.version = expected_version + 1
        return request, self.applicant_missing_fields(request)

    async def submit_review(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ):
        request = await self._get_request(session, command.request_id)
        missing = self.applicant_missing_fields(request)
        if missing:
            raise AppError(
                "MISSING_REQUIRED_FIELDS",
                f"需求人字段未完成：{', '.join(missing)}",
                400,
            )
        return await self.workflow.transition(session, current_user, command)

    async def reject(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
        reason: str,
    ):
        request = await self._get_request(session, command.request_id)
        self._require_current_handler(
            current_user,
            request,
            RoleCode.BUILDING_MANAGER,
        )
        review = await self._get_or_create_review(session, request, current_user)
        review.review_status = ReviewStatus.COMPLETED.value
        review.review_result = "REJECTED"
        review.review_opinion = reason
        review.reviewed_at = datetime.now()
        return await self.workflow.transition(session, current_user, command)

    async def save_review_fields(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        expected_version: int,
        fields: ReviewFields,
    ) -> tuple[PurchaseRequest, list[str]]:
        request = await self._get_request(session, request_id)
        self._require_current_handler(
            current_user,
            request,
            RoleCode.BUILDING_MANAGER,
        )
        if request.status != PurchaseStatus.PENDING_REVIEW.value:
            raise AppError("INVALID_STATUS", "当前状态不允许保存楼长字段", 409)
        if request.version != expected_version:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请版本已变化", 409)

        review = await self._get_or_create_review(session, request, current_user)
        values = fields.model_dump(exclude_unset=True)
        supplier_id = values.get("proposed_supplier_id")
        if supplier_id is not None:
            supplier = await self.repository.get_supplier(session, supplier_id)
            if supplier is None or not supplier.status:
                raise AppError("SUPPLIER_NOT_FOUND", "供应商不存在或已停用", 404)
            values["proposed_supplier_name"] = supplier.supplier_name

        unit_price = values.get("estimated_unit_price", review.estimated_unit_price)
        supplied_total = values.pop("estimated_total_price", None)
        if unit_price is not None:
            calculated_total = (request.quantity * unit_price).quantize(Decimal("0.01"))
            if supplied_total is not None and supplied_total != calculated_total:
                raise AppError("VALIDATION_ERROR", "预计总价与数量乘以单价不一致", 422)
            values["estimated_total_price"] = calculated_total
        elif supplied_total is not None:
            raise AppError("VALIDATION_ERROR", "填写预计总价前必须填写预计单价", 422)

        for key, value in values.items():
            setattr(review, key, value)
        updated = await self.repository.bump_version(
            session,
            request_id=request_id,
            expected_version=expected_version,
            allowed_statuses=[PurchaseStatus.PENDING_REVIEW.value],
        )
        if not updated:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请已被其他操作更新", 409)
        request.version = expected_version + 1
        await session.flush()
        return request, self.review_missing_fields(review)

    async def submit_purchaser(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ):
        review = await self.repository.get_active_review(session, command.request_id)
        if review is None:
            raise AppError("MISSING_REQUIRED_FIELDS", "尚未保存楼长审核字段", 400)
        missing = self.review_missing_fields(review)
        if missing:
            raise AppError(
                "MISSING_REQUIRED_FIELDS",
                "审批方案尚未填写完整，请补充必填信息后再提交",
                400,
                details={"fields": missing, "stage": "REVIEW"},
            )
        review.review_status = ReviewStatus.COMPLETED.value
        review.review_result = "APPROVED"
        review.reviewed_at = datetime.now()
        return await self.workflow.transition(session, current_user, command)

    async def start_purchase(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ):
        return await self.workflow.transition(session, current_user, command)

    async def save_purchase_fields(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        expected_version: int,
        fields: PurchaseFields,
    ) -> PurchaseRequest:
        request = await self._get_request(session, request_id)
        self._require_current_handler(current_user, request, RoleCode.PURCHASER)
        if request.status != PurchaseStatus.PURCHASING.value:
            raise AppError("INVALID_STATUS", "当前状态不允许保存采购字段", 409)
        if request.version != expected_version:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请版本已变化", 409)
        supplier = await self.repository.get_supplier(session, fields.supplier_id)
        if supplier is None or not supplier.status:
            raise AppError("SUPPLIER_NOT_FOUND", "供应商不存在或已停用", 404)

        calculated_total = (request.quantity * fields.actual_unit_price).quantize(Decimal("0.01"))
        if fields.actual_total_price is not None and fields.actual_total_price != calculated_total:
            raise AppError("VALIDATION_ERROR", "实际总价与数量乘以单价不一致", 422)

        execution = await self.repository.get_execution(session, request_id)
        if execution is None:
            execution = PurchaseExecution(
                request_id=request_id,
                purchaser_employee_id=current_user.employee_id,
                purchaser_platform_type_snapshot=current_user.platform_type,
                purchaser_platform_user_id_snapshot=current_user.platform_user_id,
                purchaser_name_snapshot=current_user.name,
                purchaser_mobile_snapshot=current_user.mobile,
                supplier_id=supplier.supplier_id,
                supplier_name_snapshot=supplier.supplier_name,
                supplier_tax_no_snapshot=fields.supplier_tax_number,
                supplier_bank_name_snapshot=fields.bank_name,
                supplier_bank_account_snapshot=fields.bank_account,
                supplier_address_snapshot=fields.registered_address,
                contract_contact_info_snapshot=fields.contract_contact_info,
                actual_unit_price=fields.actual_unit_price,
                actual_total_price=calculated_total,
                tax_rate=fields.tax_rate,
                purchased_at=self._naive_datetime(fields.purchased_at),
                execution_remark=fields.purchase_remark,
            )
            session.add(execution)
        else:
            execution.supplier_id = supplier.supplier_id
            execution.supplier_name_snapshot = supplier.supplier_name
            execution.supplier_tax_no_snapshot = fields.supplier_tax_number
            execution.supplier_bank_name_snapshot = fields.bank_name
            execution.supplier_bank_account_snapshot = fields.bank_account
            execution.supplier_address_snapshot = fields.registered_address
            execution.contract_contact_info_snapshot = fields.contract_contact_info
            execution.actual_unit_price = fields.actual_unit_price
            execution.actual_total_price = calculated_total
            execution.tax_rate = fields.tax_rate
            execution.purchased_at = self._naive_datetime(fields.purchased_at)
            execution.execution_remark = fields.purchase_remark

        if fields.update_supplier_profile:
            supplier.unified_social_credit_code = fields.supplier_tax_number
            supplier.bank_name = fields.bank_name
            supplier.bank_account = fields.bank_account
            supplier.registered_address = fields.registered_address
            supplier.contract_contact_info = fields.contract_contact_info

        updated = await self.repository.bump_version(
            session,
            request_id=request_id,
            expected_version=expected_version,
            allowed_statuses=[PurchaseStatus.PURCHASING.value],
        )
        if not updated:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请已被其他操作更新", 409)
        request.version = expected_version + 1
        await session.flush()
        return request

    async def submit_warehouse(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ):
        execution = await self.repository.get_execution(session, command.request_id)
        if execution is None:
            raise AppError("MISSING_REQUIRED_FIELDS", "采购员字段未完成", 400)
        return await self.workflow.transition(session, current_user, command)

    async def save_warehouse_fields(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        expected_version: int,
        fields: WarehouseFields,
    ) -> PurchaseRequest:
        request = await self._get_request(session, request_id)
        self._require_current_handler(
            current_user,
            request,
            RoleCode.WAREHOUSE_MANAGER,
        )
        if request.status != PurchaseStatus.PENDING_WAREHOUSE.value:
            raise AppError("INVALID_STATUS", "当前状态不允许保存入库字段", 409)
        if request.version != expected_version:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请版本已变化", 409)
        if fields.received_quantity < request.quantity and not fields.receipt_remark:
            raise AppError(
                "VALIDATION_ERROR",
                "入库数量少于申请数量时必须填写入库备注",
                422,
                details={"fields": ["receipt_remark"], "reason": "PARTIAL_RECEIPT"},
            )

        receipt = await self.repository.get_receipt(session, request_id)
        if receipt is None:
            receipt = WarehouseReceipt(
                request_id=request_id,
                warehouse_employee_id=current_user.employee_id,
                warehouse_platform_type_snapshot=current_user.platform_type,
                warehouse_platform_user_id_snapshot=current_user.platform_user_id,
                warehouse_name_snapshot=current_user.name,
                warehouse_mobile_snapshot=current_user.mobile,
                warehouse_location=fields.warehouse_location,
                received_quantity=fields.received_quantity,
                receipt_remark=fields.receipt_remark,
                received_at=datetime.now(),
            )
            session.add(receipt)
        else:
            receipt.warehouse_location = fields.warehouse_location
            receipt.received_quantity = fields.received_quantity
            receipt.receipt_remark = fields.receipt_remark
            receipt.received_at = datetime.now()

        updated = await self.repository.bump_version(
            session,
            request_id=request_id,
            expected_version=expected_version,
            allowed_statuses=[PurchaseStatus.PENDING_WAREHOUSE.value],
        )
        if not updated:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请已被其他操作更新", 409)
        request.version = expected_version + 1
        await session.flush()
        return request

    async def complete(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ):
        receipt = await self.repository.get_receipt(session, command.request_id)
        if receipt is None:
            raise AppError("MISSING_REQUIRED_FIELDS", "仓库入库字段未完成", 400)
        result = await self.workflow.transition(session, current_user, command)
        await self._create_completion_notifications(session, command)
        return result

    async def get_detail(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
    ) -> RequirementDetailData:
        request = await self._get_request(session, request_id)
        can_view = await self.repository.can_view_request(
            session,
            request,
            current_user.employee_id,
            current_user.has_any_role(RoleCode.ADMIN.value),
            current_user.building_ids,
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value),
        )
        if not can_view:
            raise AppError("PERMISSION_DENIED", "无权查看该采购申请", 403)
        building, handler, reviews, execution, receipt = await self.repository.get_detail_rows(
            session, request_id
        )
        can_view_bank = current_user.has_any_role(
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        execution_data = None
        if execution is not None:
            execution_data = {
                "purchaser_name": execution.purchaser_name_snapshot,
                "purchaser_mobile_masked": mask_mobile(execution.purchaser_mobile_snapshot),
                "supplier_id": execution.supplier_id,
                "supplier_name": execution.supplier_name_snapshot,
                "supplier_tax_number": execution.supplier_tax_no_snapshot,
                "bank_name": execution.supplier_bank_name_snapshot,
                "bank_account": (
                    execution.supplier_bank_account_snapshot
                    if can_view_bank
                    else mask_bank_account(execution.supplier_bank_account_snapshot)
                ),
                "registered_address": execution.supplier_address_snapshot,
                "contract_contact_info": execution.contract_contact_info_snapshot,
                "actual_unit_price": execution.actual_unit_price,
                "actual_total_price": execution.actual_total_price,
                "tax_rate": execution.tax_rate,
                "purchased_at": execution.purchased_at,
                "purchase_remark": execution.execution_remark,
            }
        return RequirementDetailData(
            requirement_id=request.request_id,
            requirement_no=request.request_no,
            status=request.status,
            version=request.version,
            building={
                "building_id": request.building_id,
                "building_name": building.building_name if building else None,
            },
            current_handler=(
                {
                    "employee_id": handler.employee_id,
                    "name": handler.name,
                    "mobile_masked": mask_mobile(handler.mobile),
                }
                if handler
                else None
            ),
            initiator={
                "name": request.applicant_name_snapshot,
                "mobile_masked": mask_mobile(request.applicant_mobile_snapshot),
                "building_name": building.building_name if building else None,
                "created_at": request.created_at,
                "operator_name": request.applicant_name_snapshot,
                "is_delegated": False,
            },
            applicant_fields={
                "device_profession": request.device_profession,
                "device_name": request.device_name,
                "brand": request.brand,
                "model": request.model,
                "quantity": request.quantity,
                "unit": request.unit,
                "application_reason": request.application_reason,
                "applicant_remark": request.applicant_remark,
            },
            review_records=[self._review_dict(review) for review in reviews],
            purchase_execution=execution_data,
            warehouse_receipt=(
                {
                    "warehouse_name": receipt.warehouse_name_snapshot,
                    "warehouse_mobile_masked": mask_mobile(receipt.warehouse_mobile_snapshot),
                    "warehouse_location": receipt.warehouse_location,
                    "received_quantity": receipt.received_quantity,
                    "receipt_remark": receipt.receipt_remark,
                    "received_at": receipt.received_at,
                }
                if receipt
                else None
            ),
            missing_fields=self._current_missing_fields(request, reviews, execution, receipt),
            allowed_actions=self._allowed_actions(current_user, request),
        )

    async def list_requirements(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        view: str,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> RequirementListData:
        if view == "BUILDING_SCOPE":
            require_any_role(
                current_user,
                RoleCode.BUILDING_MANAGER.value,
                RoleCode.ADMIN.value,
            )
        if view == "ADMIN_SCOPE":
            require_any_role(current_user, RoleCode.ADMIN.value)
        items, total = await self.repository.list_requests(
            session,
            employee_id=current_user.employee_id,
            view=view,
            status=status,
            keyword=keyword,
            building_ids=current_user.building_ids,
            page=page,
            page_size=page_size,
        )
        result_items = []
        for item in items:
            handler = await self.repository.get_employee_handler(
                session,
                item.current_handler_employee_id,
            )
            result_items.append(
                RequirementListItem(
                    requirement_id=item.request_id,
                    requirement_no=item.request_no,
                    device_name=item.device_name,
                    status=item.status,
                    current_handler_name=handler[1] if handler else None,
                )
            )
        return RequirementListData(
            items=result_items,
            page=page,
            page_size=page_size,
            total=total,
        )

    @staticmethod
    def applicant_missing_fields(request: PurchaseRequest) -> list[str]:
        return [
            field for field in APPLICANT_REQUIRED_FIELDS if getattr(request, field) in (None, "")
        ]

    @staticmethod
    def review_missing_fields(review: PurchaseReview) -> list[str]:
        missing = [
            field for field in REVIEW_REQUIRED_FIELDS if getattr(review, field) in (None, "")
        ]
        if review.proposed_supplier_id is None and not review.proposed_supplier_name:
            missing.append("proposed_supplier")
        if review.need_contract and not review.contract_type:
            missing.append("contract_type")
        return missing

    async def _get_request(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseRequest:
        request = await self.repository.get_request(session, request_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)
        return request

    @staticmethod
    def _require_current_handler(
        current_user: CurrentUser,
        request: PurchaseRequest,
        role: RoleCode,
    ) -> None:
        require_any_role(current_user, role.value)
        if request.current_handler_employee_id != current_user.employee_id:
            raise AppError("PERMISSION_DENIED", "当前用户不是采购申请处理人", 403)
        if role == RoleCode.BUILDING_MANAGER:
            require_building_membership(current_user, request.building_id)

    async def _get_or_create_review(
        self,
        session: AsyncSession,
        request: PurchaseRequest,
        current_user: CurrentUser,
    ) -> PurchaseReview:
        review = await self.repository.get_active_review(session, request.request_id)
        if review is not None:
            return review
        review = PurchaseReview(
            request_id=request.request_id,
            review_round=await self.repository.next_review_round(
                session,
                request.request_id,
            ),
            review_status=ReviewStatus.DRAFT.value,
            reviewer_employee_id=current_user.employee_id,
            reviewer_platform_type_snapshot=current_user.platform_type,
            reviewer_platform_user_id_snapshot=current_user.platform_user_id,
            reviewer_name_snapshot=current_user.name,
            reviewer_mobile_snapshot=current_user.mobile,
            need_contract=False,
        )
        session.add(review)
        await session.flush()
        return review

    async def _create_completion_notifications(
        self,
        session: AsyncSession,
        command: WorkflowCommand,
    ) -> None:
        request = await self._get_request(session, command.request_id)
        review = await self.repository.get_latest_review(session, command.request_id)
        execution = await self.repository.get_execution(session, command.request_id)
        receiver_ids = {
            request.applicant_employee_id,
            review.reviewer_employee_id if review else None,
            execution.purchaser_employee_id if execution else None,
        }
        for receiver_id in sorted(value for value in receiver_ids if value is not None):
            identities = await self.repository.get_platform_identities(
                session,
                receiver_id,
            )
            if not identities:
                continue
            platform_type, platform_user_id = identities[0]
            session.add(
                NotificationOutbox(
                    request_id=request.request_id,
                    event_type="PROCUREMENT_COMPLETED",
                    receiver_employee_id=receiver_id,
                    platform_type=platform_type,
                    receiver_platform_user_id_snapshot=platform_user_id,
                    dedup_key=f"COMPLETE:{command.action_token}:{receiver_id}",
                    payload={
                        "request_id": request.request_id,
                        "request_no": request.request_no,
                        "status": PurchaseStatus.COMPLETED.value,
                    },
                    status="PENDING",
                    retry_count=0,
                )
            )
        await session.flush()

    @staticmethod
    def _naive_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)

    @staticmethod
    def _review_dict(review: PurchaseReview) -> dict:
        return {
            "review_round": review.review_round,
            "reviewer_name": review.reviewer_name_snapshot,
            "reviewer_mobile_masked": mask_mobile(review.reviewer_mobile_snapshot),
            "review_status": review.review_status,
            "review_result": review.review_result,
            "review_opinion": review.review_opinion,
            "proposed_supplier_id": review.proposed_supplier_id,
            "proposed_supplier_name": review.proposed_supplier_name,
            "supplier_contact_name": review.supplier_contact_name,
            "supplier_contact_info": review.supplier_contact_info,
            "supplier_link": review.supplier_link,
            "estimated_unit_price": review.estimated_unit_price,
            "estimated_total_price": review.estimated_total_price,
            "need_contract": review.need_contract,
            "contract_type": review.contract_type,
            "payment_method": review.payment_method,
            "expected_arrival_date": review.expected_arrival_date,
            "warranty_info": review.warranty_info,
            "review_remark": review.review_remark,
            "reviewed_at": review.reviewed_at,
        }

    def _current_missing_fields(
        self,
        request: PurchaseRequest,
        reviews: list[PurchaseReview],
        execution: PurchaseExecution | None,
        receipt: WarehouseReceipt | None,
    ) -> list[str]:
        if request.status in {
            PurchaseStatus.DRAFT.value,
            PurchaseStatus.REJECTED.value,
        }:
            return self.applicant_missing_fields(request)
        if request.status == PurchaseStatus.PENDING_REVIEW.value:
            active = next(
                (
                    review
                    for review in reversed(reviews)
                    if review.review_status == ReviewStatus.DRAFT.value
                ),
                None,
            )
            return self.review_missing_fields(active) if active else list(REVIEW_REQUIRED_FIELDS)
        if request.status == PurchaseStatus.PURCHASING.value and execution is None:
            return ["purchase_execution"]
        if request.status == PurchaseStatus.PENDING_WAREHOUSE.value and receipt is None:
            return ["warehouse_receipt"]
        return []

    @staticmethod
    def _allowed_actions(
        current_user: CurrentUser,
        request: PurchaseRequest,
    ) -> list[str]:
        if request.current_handler_employee_id != current_user.employee_id:
            return []
        mapping = {
            PurchaseStatus.DRAFT.value: ("APPLICANT", ["SAVE_APPLICANT_FIELDS", "SUBMIT_REVIEW"]),
            PurchaseStatus.REJECTED.value: (
                "APPLICANT",
                ["SAVE_APPLICANT_FIELDS", "RESUBMIT_REVIEW"],
            ),
            PurchaseStatus.PENDING_REVIEW.value: (
                "BUILDING_MANAGER",
                [
                    "SAVE_APPLICANT_FIELDS",
                    "REJECT",
                    "SAVE_REVIEW_FIELDS",
                    "SUBMIT_PURCHASER",
                ],
            ),
            PurchaseStatus.PENDING_PURCHASE.value: ("PURCHASER", ["START_PURCHASE"]),
            PurchaseStatus.PURCHASING.value: (
                "PURCHASER",
                ["SAVE_PURCHASE_FIELDS", "SUBMIT_WAREHOUSE"],
            ),
            PurchaseStatus.PENDING_WAREHOUSE.value: (
                "WAREHOUSE_MANAGER",
                ["SAVE_WAREHOUSE_FIELDS", "COMPLETE"],
            ),
        }
        required_role, actions = mapping.get(request.status, ("", []))
        return actions if current_user.has_any_role(required_role) else []
