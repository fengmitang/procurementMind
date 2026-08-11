from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import (
    AdminOperationLog,
    Building,
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
    Role,
)
from app.models.procurement import PurchaseRequest, Supplier


class AdminRepository:
    async def list_employees(
        self,
        session: AsyncSession,
        *,
        keyword: str | None,
        status: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Employee], int]:
        statement = select(Employee)
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                Employee.name.like(pattern)
                | Employee.employee_no.like(pattern)
                | Employee.mobile.like(pattern)
            )
        if status is not None:
            statement = statement.where(Employee.status.is_(status))
        total = int(
            await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        items = list(
            (
                await session.scalars(
                    statement.order_by(Employee.updated_at.desc(), Employee.employee_id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, total

    async def get_employee(self, session: AsyncSession, employee_id: int) -> Employee | None:
        return await session.get(Employee, employee_id)

    async def employee_relations(
        self, session: AsyncSession, employee_id: int
    ) -> tuple[list[tuple], list[tuple], list[tuple]]:
        roles = list(
            (
                await session.execute(
                    select(Role.role_id, Role.role_code, Role.role_name)
                    .join(EmployeeRole, EmployeeRole.role_id == Role.role_id)
                    .where(EmployeeRole.employee_id == employee_id, EmployeeRole.status.is_(True))
                )
            ).tuples()
        )
        buildings = list(
            (
                await session.execute(
                    select(
                        Building.building_id, Building.building_name, EmployeeBuilding.is_primary
                    )
                    .join(EmployeeBuilding, EmployeeBuilding.building_id == Building.building_id)
                    .where(
                        EmployeeBuilding.employee_id == employee_id,
                        EmployeeBuilding.status.is_(True),
                    )
                )
            ).tuples()
        )
        identities = list(
            (
                await session.execute(
                    select(
                        EmployeeExternalIdentity.identity_id,
                        EmployeeExternalIdentity.platform_type,
                        EmployeeExternalIdentity.platform_user_id,
                        EmployeeExternalIdentity.status,
                    ).where(EmployeeExternalIdentity.employee_id == employee_id)
                )
            ).tuples()
        )
        return roles, buildings, identities

    async def references(self, session: AsyncSession) -> tuple[list[Role], list[Building]]:
        roles = list(
            (
                await session.scalars(
                    select(Role).where(Role.status.is_(True)).order_by(Role.role_id)
                )
            ).all()
        )
        buildings = list(
            (
                await session.scalars(
                    select(Building).where(Building.status.is_(True)).order_by(Building.building_id)
                )
            ).all()
        )
        return roles, buildings

    async def role_map(self, session: AsyncSession, role_codes: list[str]) -> dict[str, Role]:
        roles = list(
            (
                await session.scalars(
                    select(Role).where(Role.role_code.in_(role_codes), Role.status.is_(True))
                )
            ).all()
        )
        return {role.role_code: role for role in roles}

    async def valid_building_ids(self, session: AsyncSession, building_ids: list[int]) -> set[int]:
        if not building_ids:
            return set()
        return set(
            (
                await session.scalars(
                    select(Building.building_id).where(
                        Building.building_id.in_(building_ids),
                        Building.status.is_(True),
                    )
                )
            ).all()
        )

    async def replace_assignments(
        self,
        session: AsyncSession,
        employee_id: int,
        role_ids: list[int],
        building_ids: list[int],
        primary_building_id: int | None,
    ) -> None:
        await session.execute(delete(EmployeeRole).where(EmployeeRole.employee_id == employee_id))
        await session.execute(
            delete(EmployeeBuilding).where(EmployeeBuilding.employee_id == employee_id)
        )
        session.add_all(
            [
                EmployeeRole(employee_id=employee_id, role_id=value, status=True)
                for value in role_ids
            ]
        )
        session.add_all(
            [
                EmployeeBuilding(
                    employee_id=employee_id,
                    building_id=value,
                    is_primary=value == primary_building_id,
                    status=True,
                )
                for value in building_ids
            ]
        )

    async def upsert_identity(
        self,
        session: AsyncSession,
        employee_id: int,
        platform_type: str,
        platform_user_id: str,
        status: bool,
    ) -> None:
        identity = await session.scalar(
            select(EmployeeExternalIdentity).where(
                EmployeeExternalIdentity.employee_id == employee_id,
                EmployeeExternalIdentity.platform_type == platform_type,
            )
        )
        if identity is None:
            identity = EmployeeExternalIdentity(
                employee_id=employee_id,
                platform_type=platform_type,
                platform_user_id=platform_user_id,
                status=status,
            )
            session.add(identity)
        else:
            identity.platform_user_id = platform_user_id
            identity.status = status

    async def action_token_exists(self, session: AsyncSession, action_token: str) -> bool:
        return bool(
            await session.scalar(
                select(func.count())
                .select_from(AdminOperationLog)
                .where(AdminOperationLog.action_token == action_token)
            )
        )

    async def overview_counts(self, session: AsyncSession) -> tuple[int, int, int]:
        employees = int(await session.scalar(select(func.count()).select_from(Employee)) or 0)
        suppliers = int(await session.scalar(select(func.count()).select_from(Supplier)) or 0)
        requirements = int(
            await session.scalar(select(func.count()).select_from(PurchaseRequest)) or 0
        )
        return employees, suppliers, requirements

    async def recent_requirements(self, session: AsyncSession) -> list[PurchaseRequest]:
        return list(
            (
                await session.scalars(
                    select(PurchaseRequest).order_by(PurchaseRequest.updated_at.desc()).limit(8)
                )
            ).all()
        )
