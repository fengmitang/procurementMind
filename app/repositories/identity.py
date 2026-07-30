from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import (
    Building,
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
    Role,
)


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    employee: Employee
    identity: EmployeeExternalIdentity


class IdentityRepository:
    async def find_identity(
        self,
        session: AsyncSession,
        platform_type: str,
        platform_user_id: str,
    ) -> IdentityRecord | None:
        result = await session.execute(
            select(Employee, EmployeeExternalIdentity)
            .join(
                EmployeeExternalIdentity,
                EmployeeExternalIdentity.employee_id == Employee.employee_id,
            )
            .where(
                EmployeeExternalIdentity.platform_type == platform_type,
                EmployeeExternalIdentity.platform_user_id == platform_user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        employee, identity = row
        return IdentityRecord(employee=employee, identity=identity)

    async def list_roles(
        self,
        session: AsyncSession,
        employee_id: int,
    ) -> list[tuple[int, str, str]]:
        result = await session.execute(
            select(Role.role_id, Role.role_code, Role.role_name)
            .join(EmployeeRole, EmployeeRole.role_id == Role.role_id)
            .where(
                EmployeeRole.employee_id == employee_id,
                EmployeeRole.status.is_(True),
                Role.status.is_(True),
            )
            .order_by(Role.role_id)
        )
        return list(result.tuples().all())

    async def list_buildings(
        self,
        session: AsyncSession,
        employee_id: int,
    ) -> list[tuple[int, str, bool]]:
        result = await session.execute(
            select(
                Building.building_id,
                Building.building_name,
                EmployeeBuilding.is_primary,
            )
            .join(
                EmployeeBuilding,
                EmployeeBuilding.building_id == Building.building_id,
            )
            .where(
                EmployeeBuilding.employee_id == employee_id,
                EmployeeBuilding.status.is_(True),
                Building.status.is_(True),
            )
            .order_by(
                EmployeeBuilding.is_primary.desc(),
                Building.building_id,
            )
        )
        return list(result.tuples().all())
