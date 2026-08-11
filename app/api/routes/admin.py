from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.admin import (
    AdminEmployeeDeactivateRequest,
    AdminEmployeeItem,
    AdminEmployeeListData,
    AdminEmployeeMutation,
    AdminOverviewData,
    AdminReferenceData,
)
from app.services.admin import AdminService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview", response_model=ApiResponse[AdminOverviewData])
async def get_admin_overview(
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminOverviewData]:
    return ApiResponse(data=await AdminService().overview(session, current_user))


@router.get("/references", response_model=ApiResponse[AdminReferenceData])
async def get_admin_references(
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminReferenceData]:
    return ApiResponse(data=await AdminService().references(session, current_user))


@router.get("/employees", response_model=ApiResponse[AdminEmployeeListData])
async def list_admin_employees(
    current_user: CurrentUserDependency,
    session: DbSession,
    keyword: str | None = Query(default=None, min_length=1),
    status: Literal["ACTIVE", "INACTIVE"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[AdminEmployeeListData]:
    data = await AdminService().list_employees(
        session,
        current_user,
        keyword=keyword,
        status={"ACTIVE": True, "INACTIVE": False}.get(status) if status else None,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.post("/employees", response_model=ApiResponse[AdminEmployeeItem])
async def create_admin_employee(
    payload: AdminEmployeeMutation,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminEmployeeItem]:
    return ApiResponse(data=await AdminService().create_employee(session, current_user, payload))


@router.get("/employees/{employee_id}", response_model=ApiResponse[AdminEmployeeItem])
async def get_admin_employee(
    employee_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminEmployeeItem]:
    return ApiResponse(data=await AdminService().get_employee(session, current_user, employee_id))


@router.patch("/employees/{employee_id}", response_model=ApiResponse[AdminEmployeeItem])
async def update_admin_employee(
    employee_id: int,
    payload: AdminEmployeeMutation,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminEmployeeItem]:
    return ApiResponse(
        data=await AdminService().update_employee(session, current_user, employee_id, payload)
    )


@router.delete("/employees/{employee_id}", response_model=ApiResponse[AdminEmployeeItem])
async def deactivate_admin_employee(
    employee_id: int,
    payload: AdminEmployeeDeactivateRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[AdminEmployeeItem]:
    return ApiResponse(
        data=await AdminService().deactivate_employee(
            session, current_user, employee_id, payload.action_token
        )
    )
