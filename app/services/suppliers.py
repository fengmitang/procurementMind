from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser, UserRole
from app.models.procurement import (
    PurchaseOperationLog,
    Supplier,
    SupplierBlacklist,
)
from app.repositories.suppliers import SupplierRepository
from app.schemas.suppliers import (
    BlacklistCreatedData,
    BlacklistReleasedData,
    CreateBlacklistRequest,
    SupplierCreatedData,
    SupplierCreateRequest,
    SupplierDetailData,
    SupplierSearchData,
    SupplierSummaryData,
)
from app.services.permissions import require_any_role, require_building_membership
from app.services.privacy import mask_bank_account


class SupplierService:
    def __init__(self, repository: SupplierRepository | None = None) -> None:
        self.repository = repository or SupplierRepository()

    async def search(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> SupplierSearchData:
        suppliers, total = await self.repository.search(
            session,
            keyword,
            page,
            page_size,
        )
        items = []
        now = datetime.now()
        for supplier in suppliers:
            status, _ = await self.repository.blacklist_summary(
                session,
                supplier.supplier_id,
                now,
            )
            items.append(
                SupplierSummaryData(
                    supplier_id=supplier.supplier_id,
                    supplier_name=supplier.supplier_name,
                    unified_social_credit_code=supplier.unified_social_credit_code,
                    blacklist_status=status,
                )
            )
        return SupplierSearchData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_detail(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        supplier_id: int,
    ) -> SupplierDetailData:
        supplier = await self.repository.get(session, supplier_id)
        if supplier is None or not supplier.status:
            raise AppError("SUPPLIER_NOT_FOUND", "供应商不存在", 404)
        status, history_count = await self.repository.blacklist_summary(
            session,
            supplier_id,
            datetime.now(),
        )
        can_view_financial = current_user.has_any_role(
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        return SupplierDetailData(
            supplier_id=supplier.supplier_id,
            supplier_name=supplier.supplier_name,
            unified_social_credit_code=supplier.unified_social_credit_code,
            bank_name=supplier.bank_name,
            bank_account=(
                supplier.bank_account
                if can_view_financial
                else mask_bank_account(supplier.bank_account)
            ),
            registered_address=supplier.registered_address,
            contract_contact_info=supplier.contract_contact_info,
            blacklist={
                "status": status,
                "history_count": history_count,
            },
        )

    async def create(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        payload: SupplierCreateRequest,
    ) -> SupplierCreatedData:
        require_any_role(
            current_user,
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        conflict = await self.repository.find_conflict(
            session,
            payload.supplier_name,
            payload.unified_social_credit_code,
        )
        if conflict is not None:
            raise AppError(
                "SUPPLIER_MATCH_CONFLICT",
                f"存在可能重复的供应商，supplier_id={conflict.supplier_id}",
                409,
            )
        supplier = Supplier(**payload.model_dump(), status=True)
        session.add(supplier)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise AppError("SUPPLIER_MATCH_CONFLICT", "供应商名称或税号存在冲突", 409) from exc
        return SupplierCreatedData(
            supplier_id=supplier.supplier_id,
            supplier_name=supplier.supplier_name,
        )

    async def create_blacklist(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        supplier_id: int,
        payload: CreateBlacklistRequest,
    ) -> BlacklistCreatedData:
        actor_role = self._required_actor_role(
            current_user,
            RoleCode.BUILDING_MANAGER,
        )
        supplier = await session.get(Supplier, supplier_id, with_for_update=True)
        if supplier is None or not supplier.status:
            raise AppError("SUPPLIER_NOT_FOUND", "供应商不存在", 404)
        if await self.repository.action_token_exists(session, payload.action_token):
            raise AppError("DUPLICATE_OPERATION", "该操作已经执行", 409)
        request_data = await self.repository.get_completed_request_supplier(
            session,
            payload.requirement_id,
        )
        if request_data is None:
            raise AppError("INVALID_STATUS", "采购申请尚未完成或没有采购记录", 409)
        request, execution = request_data
        require_building_membership(current_user, request.building_id)
        if execution.supplier_id != supplier_id:
            raise AppError("VALIDATION_ERROR", "黑名单供应商不是本次实际采购供应商", 422)
        now = datetime.now()
        if await self.repository.has_effective_blacklist(
            session,
            supplier_id,
            now,
        ):
            raise AppError("SUPPLIER_ALREADY_BLACKLISTED", "供应商已有有效黑名单", 409)

        blacklist = SupplierBlacklist(
            supplier_id=supplier_id,
            supplier_name_snapshot=execution.supplier_name_snapshot,
            source_request_id=request.request_id,
            registrar_employee_id=current_user.employee_id,
            registrar_platform_type_snapshot=current_user.platform_type,
            registrar_platform_user_id_snapshot=current_user.platform_user_id,
            registrar_name_snapshot=current_user.name,
            registrar_mobile_snapshot=current_user.mobile,
            blacklist_type=payload.blacklist_type,
            blacklist_reason=payload.reason,
            duration_type=payload.duration_type,
            start_at=self._naive_datetime(payload.start_at),
            end_at=self._naive_datetime(payload.end_at) if payload.end_at else None,
            status="ACTIVE",
        )
        session.add(blacklist)
        await session.flush()
        self._add_log(
            session,
            current_user,
            actor_role,
            request.request_id,
            payload.action_token,
            "ADD_SUPPLIER_BLACKLIST",
            f"供应商 {supplier.supplier_name} 加入黑名单：{payload.reason}",
        )
        await session.flush()
        return BlacklistCreatedData(
            blacklist_id=blacklist.blacklist_id,
            supplier_id=supplier_id,
            status=blacklist.status,
            end_at=blacklist.end_at,
        )

    async def release_blacklist(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        supplier_id: int,
        blacklist_id: int,
        reason: str,
        action_token: str,
    ) -> BlacklistReleasedData:
        if await self.repository.action_token_exists(session, action_token):
            raise AppError("DUPLICATE_OPERATION", "该操作已经执行", 409)
        blacklist = await session.get(
            SupplierBlacklist,
            blacklist_id,
            with_for_update=True,
        )
        if blacklist is None or blacklist.supplier_id != supplier_id:
            raise AppError("BLACKLIST_NOT_FOUND", "黑名单记录不存在", 404)
        now = datetime.now()
        if blacklist.status != "ACTIVE" or (
            blacklist.duration_type == "LIMITED"
            and blacklist.end_at is not None
            and blacklist.end_at <= now
        ):
            raise AppError("INVALID_STATUS", "该黑名单当前不是有效状态", 409)

        is_admin = current_user.has_any_role(RoleCode.ADMIN.value)
        if not is_admin and blacklist.registrar_employee_id != current_user.employee_id:
            raise AppError("PERMISSION_DENIED", "仅原登记楼长或管理员可解除", 403)
        actor_role = self._required_actor_role(
            current_user,
            RoleCode.ADMIN if is_admin else RoleCode.BUILDING_MANAGER,
        )
        blacklist.status = "RELEASED"
        blacklist.released_at = now
        blacklist.released_by_employee_id = current_user.employee_id
        blacklist.release_reason = reason
        self._add_log(
            session,
            current_user,
            actor_role,
            blacklist.source_request_id,
            action_token,
            "RELEASE_SUPPLIER_BLACKLIST",
            f"提前解除供应商黑名单：{reason}",
        )
        await session.flush()
        return BlacklistReleasedData(
            blacklist_id=blacklist.blacklist_id,
            status=blacklist.status,
            released_at=now,
        )

    @staticmethod
    def _required_actor_role(
        current_user: CurrentUser,
        role_code: RoleCode,
    ) -> UserRole:
        role = next(
            (item for item in current_user.roles if item.role_code == role_code.value),
            None,
        )
        if role is None:
            raise AppError("PERMISSION_DENIED", "当前用户没有执行此操作的角色权限", 403)
        return role

    @staticmethod
    def _add_log(
        session: AsyncSession,
        current_user: CurrentUser,
        actor_role: UserRole,
        request_id: int,
        action_token: str,
        action_type: str,
        summary: str,
    ) -> None:
        session.add(
            PurchaseOperationLog(
                request_id=request_id,
                operator_employee_id=current_user.employee_id,
                operator_platform_type_snapshot=current_user.platform_type,
                operator_platform_user_id_snapshot=current_user.platform_user_id,
                operator_name_snapshot=current_user.name,
                operator_mobile_snapshot=current_user.mobile,
                operator_role_id_snapshot=actor_role.role_id,
                operator_role_name_snapshot=actor_role.role_name,
                assigned_to_employee_id=None,
                action_token=action_token,
                action_type=action_type,
                from_status="COMPLETED",
                to_status="COMPLETED",
                operation_summary=summary,
                operated_at=datetime.now(),
            )
        )

    @staticmethod
    def _naive_datetime(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo else value
