from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import (
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
    Role,
)
from app.models.procurement import PurchaseOperationLog, PurchaseRequest


class WorkflowRepository:
    async def get_request(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> PurchaseRequest | None:
        return await session.get(PurchaseRequest, request_id)

    async def action_token_exists(
        self,
        session: AsyncSession,
        action_token: str,
    ) -> bool:
        return bool(
            await session.scalar(
                select(exists().where(PurchaseOperationLog.action_token == action_token))
            )
        )

    async def is_valid_handler(
        self,
        session: AsyncSession,
        employee_id: int,
        role_code: str,
        building_id: int | None,
    ) -> bool:
        statement = select(
            exists()
            .where(
                Employee.employee_id == employee_id,
                Employee.status.is_(True),
                EmployeeRole.employee_id == Employee.employee_id,
                EmployeeRole.status.is_(True),
                Role.role_id == EmployeeRole.role_id,
                Role.role_code == role_code,
                Role.status.is_(True),
                exists().where(
                    EmployeeExternalIdentity.employee_id == Employee.employee_id,
                    EmployeeExternalIdentity.status.is_(True),
                ),
            )
            .correlate(None)
        )
        if building_id is not None:
            statement = statement.where(
                exists().where(
                    EmployeeBuilding.employee_id == employee_id,
                    EmployeeBuilding.building_id == building_id,
                    EmployeeBuilding.status.is_(True),
                )
            )
        return bool(await session.scalar(statement))

    async def advance_request(
        self,
        session: AsyncSession,
        *,
        request_id: int,
        expected_version: int,
        from_status: str,
        to_status: str,
        current_handler_employee_id: int | None,
        submitted_at: datetime | None,
        completed_at: datetime | None,
    ) -> bool:
        values: dict = {
            "status": to_status,
            "current_handler_employee_id": current_handler_employee_id,
            "version": PurchaseRequest.version + 1,
            "updated_at": datetime.now(),
        }
        if submitted_at is not None:
            values["submitted_at"] = submitted_at
        if completed_at is not None:
            values["completed_at"] = completed_at

        result = await session.execute(
            update(PurchaseRequest)
            .where(
                PurchaseRequest.request_id == request_id,
                PurchaseRequest.version == expected_version,
                PurchaseRequest.status == from_status,
            )
            .values(**values)
        )
        return result.rowcount == 1

    def add_operation_log(
        self,
        session: AsyncSession,
        operation_log: PurchaseOperationLog,
    ) -> None:
        session.add(operation_log)
