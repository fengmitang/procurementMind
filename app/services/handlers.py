from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.handlers import HandlerCandidate
from app.domain.identity import CurrentUser
from app.repositories.handlers import HandlerRepository

ASSIGNABLE_ROLES = {
    RoleCode.BUILDING_MANAGER.value,
    RoleCode.PURCHASER.value,
    RoleCode.WAREHOUSE_MANAGER.value,
}


class HandlerService:
    def __init__(self, repository: HandlerRepository | None = None) -> None:
        self.repository = repository or HandlerRepository()

    async def list_candidates(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int,
        target_role: str,
    ) -> list[HandlerCandidate]:
        normalized_role = target_role.upper()
        if normalized_role not in ASSIGNABLE_ROLES:
            raise AppError("INVALID_TARGET_ROLE", "目标角色不可作为流程处理人", 400)

        purchase_request = await self.repository.get_request(session, request_id)
        if purchase_request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)

        can_view = (
            current_user.has_any_role(RoleCode.ADMIN.value)
            or purchase_request.applicant_employee_id == current_user.employee_id
            or purchase_request.current_handler_employee_id == current_user.employee_id
            or (
                current_user.has_any_role(RoleCode.BUILDING_MANAGER.value)
                and current_user.belongs_to_building(purchase_request.building_id)
            )
        )
        if not can_view:
            raise AppError("PERMISSION_DENIED", "无权查看该采购申请的处理人候选", 403)

        building_id = (
            purchase_request.building_id
            if normalized_role == RoleCode.BUILDING_MANAGER.value
            else None
        )
        return await self.repository.list_candidates(
            session,
            normalized_role,
            building_id,
        )
