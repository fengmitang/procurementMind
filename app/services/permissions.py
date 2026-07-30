from app.core.exceptions import AppError
from app.domain.identity import CurrentUser


def require_any_role(user: CurrentUser, *role_codes: str) -> None:
    if not user.has_any_role(*role_codes):
        raise AppError("PERMISSION_DENIED", "当前用户没有执行此操作的角色权限", 403)


def require_building_membership(user: CurrentUser, building_id: int) -> None:
    if not user.belongs_to_building(building_id):
        raise AppError("BUILDING_NOT_ALLOWED", "当前用户无权访问该楼宇", 403)
