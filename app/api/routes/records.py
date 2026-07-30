from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.records import (
    PurchaseRecordListData,
    TimelineContactData,
    TimelineData,
)
from app.services.records import PurchaseRecordService

router = APIRouter(tags=["purchase-records"])


@router.get(
    "/api/v1/purchase-records",
    response_model=ApiResponse[PurchaseRecordListData],
)
async def list_purchase_records(
    current_user: CurrentUserDependency,
    session: DbSession,
    requirement_no: str | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    model: str | None = Query(default=None),
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[PurchaseRecordListData]:
    data = await PurchaseRecordService().list_records(
        session,
        current_user,
        requirement_no=requirement_no,
        supplier_id=supplier_id,
        status=status,
        device_name=device_name,
        brand=brand,
        model=model,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.get(
    "/api/v1/requirements/{requirement_id}/timeline",
    response_model=ApiResponse[TimelineData],
)
async def get_requirement_timeline(
    requirement_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[TimelineData]:
    data = await PurchaseRecordService().timeline(
        session,
        current_user,
        requirement_id,
    )
    return ApiResponse(data=data)


@router.get(
    "/api/v1/requirements/{requirement_id}/timeline/{log_id}/contact",
    response_model=ApiResponse[TimelineContactData],
)
async def get_timeline_contact(
    requirement_id: int,
    log_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
    subject: Literal["operator", "assignee"] = Query(default="operator"),
) -> ApiResponse[TimelineContactData]:
    data = await PurchaseRecordService().timeline_contact(
        session,
        current_user,
        requirement_id,
        log_id,
        subject,
    )
    return ApiResponse(data=data)
