from pydantic import BaseModel


class UserRoleData(BaseModel):
    role_id: int
    role_code: str
    role_name: str


class UserBuildingData(BaseModel):
    building_id: int
    building_name: str
    is_primary: bool


class CurrentUserData(BaseModel):
    employee_id: int
    employee_no: str | None
    name: str
    mobile: str | None
    status: str
    platform_type: str
    platform_user_id: str
    roles: list[UserRoleData]
    buildings: list[UserBuildingData]
