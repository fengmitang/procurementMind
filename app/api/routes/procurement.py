from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.domain.workflow import WorkflowCommand, WorkflowOperation
from app.schemas.procurement import (
    ActionRequest,
    AssignedActionRequest,
    CreateRequirementRequest,
    CurrentHandlerData,
    FieldsSaveData,
    RejectRequest,
    RequirementDetailData,
    RequirementListData,
    RequirementMutationData,
    SaveApplicantFieldsRequest,
    SavePurchaseFieldsRequest,
    SaveReviewFieldsRequest,
    SaveWarehouseFieldsRequest,
)
from app.services.procurement import ProcurementService

router = APIRouter(prefix="/api/v1/requirements", tags=["requirements"])


async def mutation_response(
    service: ProcurementService,
    session: DbSession,
    *,
    request_id: int,
    status: str,
    version: int,
    handler_id: int | None,
    requirement_no: str | None = None,
    completed_at=None,
) -> ApiResponse[RequirementMutationData]:
    handler_data = None
    if handler_id is not None:
        handler = await service.repository.get_employee_handler(session, handler_id)
        identities = await service.repository.get_platform_identities(session, handler_id)
        if handler is not None:
            handler_data = CurrentHandlerData(
                employee_id=handler[0],
                name=handler[1],
                platform_identities=[
                    {
                        "platform_type": platform_type,
                        "platform_user_id": platform_user_id,
                    }
                    for platform_type, platform_user_id in identities
                ],
            )
    return ApiResponse(
        data=RequirementMutationData(
            requirement_id=request_id,
            requirement_no=requirement_no,
            status=status,
            version=version,
            current_handler=handler_data,
            completed_at=completed_at,
        )
    )


@router.post("", response_model=ApiResponse[RequirementMutationData])
async def create_requirement(
    payload: CreateRequirementRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    request = await service.create_draft(session, current_user, payload.building_id)
    return await mutation_response(
        service,
        session,
        request_id=request.request_id,
        requirement_no=request.request_no,
        status=request.status,
        version=request.version,
        handler_id=request.current_handler_employee_id,
    )


@router.patch(
    "/{requirement_id}/applicant-fields",
    response_model=ApiResponse[FieldsSaveData],
)
async def save_applicant_fields(
    requirement_id: int,
    payload: SaveApplicantFieldsRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[FieldsSaveData]:
    request, missing = await ProcurementService().save_applicant_fields(
        session,
        current_user,
        requirement_id,
        payload.expected_version,
        payload.fields,
    )
    return ApiResponse(
        data=FieldsSaveData(
            requirement_id=requirement_id,
            status=request.status,
            version=request.version,
            missing_fields=missing,
            next_missing_field=missing[0] if missing else None,
            fields_complete=not missing,
        )
    )


@router.get("", response_model=ApiResponse[RequirementListData])
async def list_requirements(
    current_user: CurrentUserDependency,
    session: DbSession,
    view: Literal[
        "CREATED_BY_ME",
        "PENDING_FOR_ME",
        "PROCESSED_BY_ME",
        "BUILDING_SCOPE",
        "ADMIN_SCOPE",
    ] = Query(),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, min_length=1, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[RequirementListData]:
    data = await ProcurementService().list_requirements(
        session,
        current_user,
        view=view,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=data)


@router.get(
    "/{requirement_id}",
    response_model=ApiResponse[RequirementDetailData],
)
async def get_requirement_detail(
    requirement_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementDetailData]:
    data = await ProcurementService().get_detail(
        session,
        current_user,
        requirement_id,
    )
    return ApiResponse(data=data)


@router.post(
    "/{requirement_id}/submit-review",
    response_model=ApiResponse[RequirementMutationData],
)
async def submit_review(
    requirement_id: int,
    payload: AssignedActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.submit_review(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.SUBMIT_REVIEW,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
            assigned_to_employee_id=payload.assigned_to_employee_id,
        ),
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.post(
    "/{requirement_id}/reject",
    response_model=ApiResponse[RequirementMutationData],
)
async def reject_requirement(
    requirement_id: int,
    payload: RejectRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.reject(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.REJECT,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
            operation_summary=payload.reason,
        ),
        payload.reason,
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.post(
    "/{requirement_id}/resubmit-review",
    response_model=ApiResponse[RequirementMutationData],
)
async def resubmit_review(
    requirement_id: int,
    payload: AssignedActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.submit_review(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.RESUBMIT_REVIEW,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
            assigned_to_employee_id=payload.assigned_to_employee_id,
        ),
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.patch(
    "/{requirement_id}/review-fields",
    response_model=ApiResponse[FieldsSaveData],
)
async def save_review_fields(
    requirement_id: int,
    payload: SaveReviewFieldsRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[FieldsSaveData]:
    request, missing = await ProcurementService().save_review_fields(
        session,
        current_user,
        requirement_id,
        payload.expected_version,
        payload.fields,
    )
    return ApiResponse(
        data=FieldsSaveData(
            requirement_id=requirement_id,
            status=request.status,
            version=request.version,
            missing_fields=missing,
            next_missing_field=missing[0] if missing else None,
            fields_complete=not missing,
        )
    )


@router.post(
    "/{requirement_id}/submit-purchaser",
    response_model=ApiResponse[RequirementMutationData],
)
async def submit_purchaser(
    requirement_id: int,
    payload: AssignedActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.submit_purchaser(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.SUBMIT_PURCHASER,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
            assigned_to_employee_id=payload.assigned_to_employee_id,
        ),
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.post(
    "/{requirement_id}/start-purchase",
    response_model=ApiResponse[RequirementMutationData],
)
async def start_purchase(
    requirement_id: int,
    payload: ActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.start_purchase(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.START_PURCHASE,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
        ),
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.patch(
    "/{requirement_id}/purchase-fields",
    response_model=ApiResponse[FieldsSaveData],
)
async def save_purchase_fields(
    requirement_id: int,
    payload: SavePurchaseFieldsRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[FieldsSaveData]:
    request = await ProcurementService().save_purchase_fields(
        session,
        current_user,
        requirement_id,
        payload.expected_version,
        payload.fields,
    )
    return ApiResponse(
        data=FieldsSaveData(
            requirement_id=requirement_id,
            status=request.status,
            version=request.version,
            missing_fields=[],
            fields_complete=True,
        )
    )


@router.post(
    "/{requirement_id}/submit-warehouse",
    response_model=ApiResponse[RequirementMutationData],
)
async def submit_warehouse(
    requirement_id: int,
    payload: AssignedActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.submit_warehouse(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.SUBMIT_WAREHOUSE,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
            assigned_to_employee_id=payload.assigned_to_employee_id,
        ),
    )
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
    )


@router.patch(
    "/{requirement_id}/warehouse-fields",
    response_model=ApiResponse[FieldsSaveData],
)
async def save_warehouse_fields(
    requirement_id: int,
    payload: SaveWarehouseFieldsRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[FieldsSaveData]:
    request = await ProcurementService().save_warehouse_fields(
        session,
        current_user,
        requirement_id,
        payload.expected_version,
        payload.fields,
    )
    return ApiResponse(
        data=FieldsSaveData(
            requirement_id=requirement_id,
            status=request.status,
            version=request.version,
            missing_fields=[],
            fields_complete=True,
        )
    )


@router.post(
    "/{requirement_id}/complete",
    response_model=ApiResponse[RequirementMutationData],
)
async def complete_requirement(
    requirement_id: int,
    payload: ActionRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementMutationData]:
    service = ProcurementService()
    result = await service.complete(
        session,
        current_user,
        WorkflowCommand(
            request_id=requirement_id,
            operation=WorkflowOperation.COMPLETE,
            expected_version=payload.expected_version,
            action_token=payload.action_token,
        ),
    )
    request = await service.repository.get_request(session, requirement_id)
    return await mutation_response(
        service,
        session,
        request_id=requirement_id,
        status=result.status,
        version=result.version,
        handler_id=result.current_handler_employee_id,
        completed_at=request.completed_at if request else None,
    )
