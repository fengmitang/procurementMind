from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.handlers import HandlerCandidateData, HandlerCandidateListData
from app.services.handlers import HandlerService
from app.services.privacy import mask_mobile

router = APIRouter(prefix="/api/v1/requirements", tags=["requirements"])


@router.get(
    "/{requirement_id}/handler-candidates",
    response_model=ApiResponse[HandlerCandidateListData],
)
async def get_handler_candidates(
    requirement_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
    target_role: str = Query(),
) -> ApiResponse[HandlerCandidateListData]:
    candidates = await HandlerService().list_candidates(
        session,
        current_user,
        requirement_id,
        target_role,
    )
    return ApiResponse(
        data=HandlerCandidateListData(
            items=[
                HandlerCandidateData(
                    employee_id=candidate.employee_id,
                    name=candidate.name,
                    mobile=mask_mobile(candidate.mobile),
                )
                for candidate in candidates
            ],
            auto_selected_employee_id=(candidates[0].employee_id if len(candidates) == 1 else None),
        )
    )
