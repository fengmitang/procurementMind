from fastapi import APIRouter

from app.api.dependencies import CurrentUserDependency
from app.core.responses import ApiResponse
from app.schemas.identity import CurrentUserData, UserBuildingData, UserRoleData
from app.services.privacy import mask_mobile

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=ApiResponse[CurrentUserData])
async def get_me(current_user: CurrentUserDependency) -> ApiResponse[CurrentUserData]:
    return ApiResponse(
        data=CurrentUserData(
            employee_id=current_user.employee_id,
            employee_no=current_user.employee_no,
            name=current_user.name,
            mobile=mask_mobile(current_user.mobile),
            status="ACTIVE",
            platform_type=current_user.platform_type,
            platform_user_id=current_user.platform_user_id,
            roles=[
                UserRoleData(
                    role_id=role.role_id,
                    role_code=role.role_code,
                    role_name=role.role_name,
                )
                for role in current_user.roles
            ],
            buildings=[
                UserBuildingData(
                    building_id=building.building_id,
                    building_name=building.building_name,
                    is_primary=building.is_primary,
                )
                for building in current_user.buildings
            ],
        )
    )
