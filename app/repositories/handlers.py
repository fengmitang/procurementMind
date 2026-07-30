from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.handlers import HandlerCandidate
from app.models.identity import (
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
    Role,
)
from app.models.procurement import PurchaseRequest


class HandlerRepository:
    async def get_request(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseRequest | None:
        return await session.get(PurchaseRequest, request_id)

    async def list_candidates(
        self,
        session: AsyncSession,
        role_code: str,
        building_id: int | None,
    ) -> list[HandlerCandidate]:
        statement = (
            select(Employee.employee_id, Employee.name, Employee.mobile)
            .join(EmployeeRole, EmployeeRole.employee_id == Employee.employee_id)
            .join(Role, Role.role_id == EmployeeRole.role_id)
            .where(
                Employee.status.is_(True),
                EmployeeRole.status.is_(True),
                Role.status.is_(True),
                Role.role_code == role_code,
                exists().where(
                    EmployeeExternalIdentity.employee_id == Employee.employee_id,
                    EmployeeExternalIdentity.status.is_(True),
                ),
            )
        )
        if building_id is not None:
            statement = statement.join(
                EmployeeBuilding,
                EmployeeBuilding.employee_id == Employee.employee_id,
            ).where(
                EmployeeBuilding.building_id == building_id,
                EmployeeBuilding.status.is_(True),
            )

        result = await session.execute(statement.distinct().order_by(Employee.employee_id))
        return [
            HandlerCandidate(
                employee_id=employee_id,
                name=name,
                mobile=mobile,
            )
            for employee_id, name, mobile in result.tuples()
        ]
