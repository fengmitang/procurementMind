from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class SupplierCreateRequest(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=200)
    unified_social_credit_code: str | None = Field(default=None, max_length=50)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_account: str | None = Field(default=None, max_length=255)
    registered_address: str | None = Field(default=None, max_length=500)
    contract_contact_info: str | None = Field(default=None, max_length=255)


class SupplierSummaryData(BaseModel):
    supplier_id: int
    supplier_name: str
    unified_social_credit_code: str | None
    blacklist_status: str
    status: bool


class SupplierSearchData(BaseModel):
    items: list[SupplierSummaryData]
    page: int
    page_size: int
    total: int


class SupplierRiskItem(BaseModel):
    blacklist_id: int
    supplier_id: int
    supplier_name: str
    blacklist_type: str
    risk_reason: str
    status: str
    start_at: datetime
    end_at: datetime | None
    released_at: datetime | None
    release_reason: str | None
    is_effective: bool
    source_requirement_id: int
    source_requirement_no: str


class SupplierRiskListData(BaseModel):
    items: list[SupplierRiskItem]
    page: int
    page_size: int
    total: int


class SupplierBlacklistSummary(BaseModel):
    status: str
    history_count: int


class SupplierDetailData(BaseModel):
    supplier_id: int
    supplier_name: str
    unified_social_credit_code: str | None
    bank_name: str | None
    bank_account: str | None
    registered_address: str | None
    contract_contact_info: str | None
    blacklist: SupplierBlacklistSummary


class SupplierCreatedData(BaseModel):
    supplier_id: int
    supplier_name: str


class CreateBlacklistRequest(BaseModel):
    requirement_id: int
    blacklist_type: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1)
    duration_type: str
    start_at: datetime
    end_at: datetime | None = None
    action_token: str = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def validate_duration(self) -> "CreateBlacklistRequest":
        self.duration_type = self.duration_type.upper()
        if self.duration_type not in {"PERMANENT", "LIMITED"}:
            raise ValueError("duration_type 必须是 PERMANENT 或 LIMITED")
        if self.duration_type == "PERMANENT" and self.end_at is not None:
            raise ValueError("永久黑名单不能填写 end_at")
        if self.duration_type == "LIMITED" and self.end_at is None:
            raise ValueError("限时黑名单必须填写 end_at")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at 必须晚于 start_at")
        return self


class BlacklistCreatedData(BaseModel):
    blacklist_id: int
    supplier_id: int
    status: str
    end_at: datetime | None


class ReleaseBlacklistRequest(BaseModel):
    reason: str = Field(min_length=1)
    action_token: str = Field(min_length=8, max_length=64)


class BlacklistReleasedData(BaseModel):
    blacklist_id: int
    status: str
    released_at: datetime
