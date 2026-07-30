from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.gateway_auth import GatewayIdentity
from app.domain.identity import CurrentUser, UserBuilding, UserRole
from app.repositories.identity import IdentityRepository


class IdentityService:
    def __init__(self, repository: IdentityRepository | None = None) -> None:
        self.repository = repository or IdentityRepository()

    async def resolve_current_user(
        self,
        session: AsyncSession,
        gateway_identity: GatewayIdentity,
    ) -> CurrentUser:
        record = await self.repository.find_identity(
            session,
            gateway_identity.platform_type,
            gateway_identity.platform_user_id,
        )
        if record is None:
            raise AppError("USER_NOT_FOUND", "平台身份尚未绑定员工", 404)
        if not record.employee.status or not record.identity.status:
            raise AppError("USER_DISABLED", "员工账号已停用", 403)

        roles = await self.repository.list_roles(session, record.employee.employee_id)
        buildings = await self.repository.list_buildings(
            session,
            record.employee.employee_id,
        )
        return CurrentUser(
            employee_id=record.employee.employee_id,
            employee_no=record.employee.employee_no,
            name=record.employee.name,
            mobile=record.employee.mobile,
            platform_type=gateway_identity.platform_type,
            platform_user_id=gateway_identity.platform_user_id,
            roles=tuple(
                UserRole(role_id=role_id, role_code=role_code, role_name=role_name)
                for role_id, role_code, role_name in roles
            ),
            buildings=tuple(
                UserBuilding(
                    building_id=building_id,
                    building_name=building_name,
                    is_primary=is_primary,
                )
                for building_id, building_name, is_primary in buildings
            ),
        )
