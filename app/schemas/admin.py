from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminEmployeeMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_no: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    mobile: str | None = Field(default=None, max_length=64)
    status: bool = True
    role_codes: list[str] = Field(min_length=1, max_length=10)
    building_ids: list[int] = Field(default_factory=list, max_length=50)
    primary_building_id: int | None = None
    platform_type: str = Field(default="TEST_PLATFORM", min_length=1, max_length=30)
    platform_user_id: str = Field(min_length=1, max_length=150)
    action_token: str = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def primary_building_must_be_assigned(self) -> "AdminEmployeeMutation":
        if (
            self.primary_building_id is not None
            and self.primary_building_id not in self.building_ids
        ):
            raise ValueError("主楼宇必须包含在所属楼宇中")
        self.role_codes = sorted(set(code.upper() for code in self.role_codes))
        self.building_ids = sorted(set(self.building_ids))
        self.platform_type = self.platform_type.upper()
        return self


class AdminEmployeeDeactivateRequest(BaseModel):
    action_token: str = Field(min_length=8, max_length=64)


class AdminEmployeeItem(BaseModel):
    employee_id: int
    employee_no: str | None
    name: str
    mobile: str | None
    status: bool
    roles: list[dict[str, object]]
    buildings: list[dict[str, object]]
    identities: list[dict[str, object]]
    created_at: datetime
    updated_at: datetime


class AdminEmployeeListData(BaseModel):
    items: list[AdminEmployeeItem]
    page: int
    page_size: int
    total: int


class AdminReferenceData(BaseModel):
    roles: list[dict[str, object]]
    buildings: list[dict[str, object]]


class AdminOverviewData(BaseModel):
    employee_count: int
    supplier_count: int
    requirement_count: int
    recent_employees: list[AdminEmployeeItem]
    recent_requirements: list[dict[str, object]]
