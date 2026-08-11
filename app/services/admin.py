from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.models.identity import AdminOperationLog, Employee, EmployeeExternalIdentity
from app.repositories.admin import AdminRepository
from app.schemas.admin import (
    AdminEmployeeItem,
    AdminEmployeeListData,
    AdminEmployeeMutation,
    AdminOverviewData,
    AdminReferenceData,
)
from app.services.permissions import require_any_role


class AdminService:
    def __init__(self, repository: AdminRepository | None = None) -> None:
        self.repository = repository or AdminRepository()

    @staticmethod
    def require_admin(current_user: CurrentUser) -> None:
        require_any_role(current_user, RoleCode.ADMIN.value)

    async def list_employees(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        keyword: str | None,
        status: bool | None,
        page: int,
        page_size: int,
    ) -> AdminEmployeeListData:
        self.require_admin(current_user)
        employees, total = await self.repository.list_employees(
            session,
            keyword=keyword,
            status=status,
            page=page,
            page_size=page_size,
        )
        return AdminEmployeeListData(
            items=[await self._item(session, employee) for employee in employees],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_employee(
        self, session: AsyncSession, current_user: CurrentUser, employee_id: int
    ) -> AdminEmployeeItem:
        self.require_admin(current_user)
        employee = await self.repository.get_employee(session, employee_id)
        if employee is None:
            raise AppError("EMPLOYEE_NOT_FOUND", "员工不存在", 404)
        return await self._item(session, employee)

    async def references(
        self, session: AsyncSession, current_user: CurrentUser
    ) -> AdminReferenceData:
        self.require_admin(current_user)
        roles, buildings = await self.repository.references(session)
        return AdminReferenceData(
            roles=[
                {"role_id": item.role_id, "role_code": item.role_code, "role_name": item.role_name}
                for item in roles
            ],
            buildings=[
                {"building_id": item.building_id, "building_name": item.building_name}
                for item in buildings
            ],
        )

    async def create_employee(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        payload: AdminEmployeeMutation,
    ) -> AdminEmployeeItem:
        self.require_admin(current_user)
        await self._require_new_action(session, payload.action_token)
        role_map = await self._validated_role_map(session, payload.role_codes)
        await self._validate_buildings(session, payload.building_ids)
        employee = Employee(
            employee_no=payload.employee_no,
            name=payload.name,
            mobile=payload.mobile,
            status=payload.status,
        )
        session.add(employee)
        try:
            await session.flush()
            await self.repository.replace_assignments(
                session,
                employee.employee_id,
                [role_map[code].role_id for code in payload.role_codes],
                payload.building_ids,
                payload.primary_building_id,
            )
            await self.repository.upsert_identity(
                session,
                employee.employee_id,
                payload.platform_type,
                payload.platform_user_id,
                payload.status,
            )
            self._log_action(
                session,
                current_user.employee_id,
                employee.employee_id,
                "CREATE_EMPLOYEE",
                payload.action_token,
            )
            await session.flush()
        except IntegrityError as exc:
            raise AppError(
                "EMPLOYEE_IDENTITY_CONFLICT",
                "员工编号或平台账号已被使用，请检查后重试",
                409,
            ) from exc
        await session.refresh(employee)
        return await self._item(session, employee)

    async def update_employee(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        employee_id: int,
        payload: AdminEmployeeMutation,
    ) -> AdminEmployeeItem:
        self.require_admin(current_user)
        await self._require_new_action(session, payload.action_token)
        employee = await self.repository.get_employee(session, employee_id)
        if employee is None:
            raise AppError("EMPLOYEE_NOT_FOUND", "员工不存在", 404)
        role_map = await self._validated_role_map(session, payload.role_codes)
        await self._validate_buildings(session, payload.building_ids)
        employee.employee_no = payload.employee_no
        employee.name = payload.name
        employee.mobile = payload.mobile
        employee.status = payload.status
        try:
            await self.repository.replace_assignments(
                session,
                employee_id,
                [role_map[code].role_id for code in payload.role_codes],
                payload.building_ids,
                payload.primary_building_id,
            )
            await self.repository.upsert_identity(
                session,
                employee_id,
                payload.platform_type,
                payload.platform_user_id,
                payload.status,
            )
            self._log_action(
                session,
                current_user.employee_id,
                employee_id,
                "UPDATE_EMPLOYEE",
                payload.action_token,
            )
            await session.flush()
        except IntegrityError as exc:
            raise AppError(
                "EMPLOYEE_IDENTITY_CONFLICT",
                "员工编号或平台账号已被使用，请检查后重试",
                409,
            ) from exc
        await session.refresh(employee)
        return await self._item(session, employee)

    async def deactivate_employee(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        employee_id: int,
        action_token: str,
    ) -> AdminEmployeeItem:
        self.require_admin(current_user)
        if employee_id == current_user.employee_id:
            raise AppError("ADMIN_SELF_DISABLE_FORBIDDEN", "不能停用当前登录的管理员账号", 409)
        await self._require_new_action(session, action_token)
        employee = await self.repository.get_employee(session, employee_id)
        if employee is None:
            raise AppError("EMPLOYEE_NOT_FOUND", "员工不存在", 404)
        employee.status = False
        _, _, identities = await self.repository.employee_relations(session, employee_id)
        for identity in identities:
            model = await session.get(EmployeeExternalIdentity, identity[0])
            if model is not None:
                model.status = False
        self._log_action(
            session,
            current_user.employee_id,
            employee_id,
            "DEACTIVATE_EMPLOYEE",
            action_token,
        )
        await session.flush()
        await session.refresh(employee)
        return await self._item(session, employee)

    async def overview(self, session: AsyncSession, current_user: CurrentUser) -> AdminOverviewData:
        self.require_admin(current_user)
        employee_count, supplier_count, requirement_count = await self.repository.overview_counts(
            session
        )
        recent_employees, _ = await self.repository.list_employees(
            session, keyword=None, status=None, page=1, page_size=6
        )
        recent_requirements = await self.repository.recent_requirements(session)
        return AdminOverviewData(
            employee_count=employee_count,
            supplier_count=supplier_count,
            requirement_count=requirement_count,
            recent_employees=[await self._item(session, item) for item in recent_employees],
            recent_requirements=[
                {
                    "requirement_id": item.request_id,
                    "requirement_no": item.request_no,
                    "device_name": item.device_name,
                    "status": item.status,
                    "updated_at": item.updated_at,
                }
                for item in recent_requirements
            ],
        )

    async def _item(self, session: AsyncSession, employee: Employee) -> AdminEmployeeItem:
        roles, buildings, identities = await self.repository.employee_relations(
            session, employee.employee_id
        )
        return AdminEmployeeItem(
            employee_id=employee.employee_id,
            employee_no=employee.employee_no,
            name=employee.name,
            mobile=employee.mobile,
            status=employee.status,
            roles=[{"role_id": row[0], "role_code": row[1], "role_name": row[2]} for row in roles],
            buildings=[
                {"building_id": row[0], "building_name": row[1], "is_primary": row[2]}
                for row in buildings
            ],
            identities=[
                {
                    "identity_id": row[0],
                    "platform_type": row[1],
                    "platform_user_id": row[2],
                    "status": row[3],
                }
                for row in identities
            ],
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )

    async def _validated_role_map(self, session: AsyncSession, codes: list[str]):
        values = await self.repository.role_map(session, codes)
        missing = sorted(set(codes) - values.keys())
        if missing:
            raise AppError("ROLE_NOT_FOUND", "选择的员工角色无效，请刷新后重试", 422)
        return values

    async def _validate_buildings(self, session: AsyncSession, building_ids: list[int]) -> None:
        valid_ids = await self.repository.valid_building_ids(session, building_ids)
        if set(building_ids) != valid_ids:
            raise AppError(
                "BUILDING_NOT_FOUND",
                "选择的所属楼宇无效，请刷新后重新选择",
                422,
            )

    async def _require_new_action(self, session: AsyncSession, action_token: str) -> None:
        if await self.repository.action_token_exists(session, action_token):
            raise AppError("DUPLICATE_ACTION", "该操作已经提交，请勿重复操作", 409)

    @staticmethod
    def _log_action(
        session: AsyncSession,
        admin_employee_id: int,
        target_employee_id: int,
        action_type: str,
        action_token: str,
    ) -> None:
        session.add(
            AdminOperationLog(
                admin_employee_id=admin_employee_id,
                target_employee_id=target_employee_id,
                action_type=action_type,
                action_token=action_token,
            )
        )
