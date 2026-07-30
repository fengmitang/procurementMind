from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.suppliers import (
    BlacklistCreatedData,
    BlacklistReleasedData,
    CreateBlacklistRequest,
    ReleaseBlacklistRequest,
    SupplierCreatedData,
    SupplierCreateRequest,
    SupplierDetailData,
    SupplierSearchData,
)
from app.services.suppliers import SupplierService

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])


@router.get("", response_model=ApiResponse[SupplierSearchData])
async def search_suppliers(
    current_user: CurrentUserDependency,
    session: DbSession,
    keyword: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[SupplierSearchData]:
    data = await SupplierService().search(
        session,
        current_user,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.get("/{supplier_id}", response_model=ApiResponse[SupplierDetailData])
async def get_supplier(
    supplier_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[SupplierDetailData]:
    data = await SupplierService().get_detail(
        session,
        current_user,
        supplier_id,
    )
    return ApiResponse(data=data)


@router.post("", response_model=ApiResponse[SupplierCreatedData])
async def create_supplier(
    payload: SupplierCreateRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[SupplierCreatedData]:
    data = await SupplierService().create(session, current_user, payload)
    return ApiResponse(data=data)


@router.post(
    "/{supplier_id}/blacklist",
    response_model=ApiResponse[BlacklistCreatedData],
)
async def create_supplier_blacklist(
    supplier_id: int,
    payload: CreateBlacklistRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[BlacklistCreatedData]:
    data = await SupplierService().create_blacklist(
        session,
        current_user,
        supplier_id,
        payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/{supplier_id}/blacklists/{blacklist_id}/release",
    response_model=ApiResponse[BlacklistReleasedData],
)
async def release_supplier_blacklist(
    supplier_id: int,
    blacklist_id: int,
    payload: ReleaseBlacklistRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[BlacklistReleasedData]:
    data = await SupplierService().release_blacklist(
        session,
        current_user,
        supplier_id,
        blacklist_id,
        payload.reason,
        payload.action_token,
    )
    return ApiResponse(data=data)
