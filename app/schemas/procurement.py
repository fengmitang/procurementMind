from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

DEVICE_PROFESSIONS = (
    "10kV开关柜",
    "变压器",
    "400V配电柜",
    "UPS",
    "高压直流",
    "蓄电池",
    "监控",
    "冷水机组",
    "SHU",
    "冷却塔",
    "冷却泵",
    "机房环境",
    "水系统",
    "传输",
    "服务器",
    "运维工具",
    "列间空调",
)

DeviceType = Literal[*DEVICE_PROFESSIONS]


class CreateRequirementRequest(BaseModel):
    building_id: int


class ApplicantFields(BaseModel):
    device_profession: DeviceType | None = None
    device_name: str | None = Field(default=None, max_length=200)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=150)
    quantity: int | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=30)
    application_reason: str | None = None
    applicant_remark: str | None = None


class SaveApplicantFieldsRequest(BaseModel):
    expected_version: int = Field(ge=0)
    fields: ApplicantFields


class AssignedActionRequest(BaseModel):
    expected_version: int = Field(ge=0)
    assigned_to_employee_id: int
    action_token: str = Field(min_length=8, max_length=64)


class ActionRequest(BaseModel):
    expected_version: int = Field(ge=0)
    action_token: str = Field(min_length=8, max_length=64)


class RejectRequest(ActionRequest):
    reason: str = Field(min_length=1)


class ReviewFields(BaseModel):
    proposed_supplier_id: int | None = None
    proposed_supplier_name: str | None = Field(default=None, max_length=200)
    supplier_contact_name: str | None = Field(default=None, max_length=100)
    supplier_contact_info: str | None = Field(default=None, max_length=255)
    supplier_link: str | None = Field(default=None, max_length=1000)
    estimated_unit_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    estimated_total_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    need_contract: bool | None = None
    contract_type: str | None = Field(default=None, max_length=100)
    payment_method: str | None = Field(default=None, max_length=100)
    expected_arrival_date: date | None = None
    warranty_info: str | None = Field(default=None, max_length=255)
    review_remark: str | None = None


class SaveReviewFieldsRequest(BaseModel):
    expected_version: int = Field(ge=0)
    fields: ReviewFields


class PurchaseFields(BaseModel):
    supplier_id: int
    supplier_tax_number: str | None = Field(default=None, max_length=50)
    bank_name: str | None = Field(default=None, max_length=200)
    bank_account: str | None = Field(default=None, max_length=255)
    registered_address: str | None = Field(default=None, max_length=500)
    contract_contact_info: str | None = Field(default=None, max_length=255)
    actual_unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    actual_total_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    purchased_at: datetime
    purchase_remark: str | None = None
    update_supplier_profile: bool = False


class SavePurchaseFieldsRequest(BaseModel):
    expected_version: int = Field(ge=0)
    fields: PurchaseFields


class WarehouseFields(BaseModel):
    warehouse_location: str = Field(min_length=1, max_length=255)
    received_quantity: int = Field(gt=0)
    receipt_remark: str | None = None


class SaveWarehouseFieldsRequest(BaseModel):
    expected_version: int = Field(ge=0)
    fields: WarehouseFields


class CurrentHandlerData(BaseModel):
    employee_id: int
    name: str
    platform_identities: list[dict[str, str]] = Field(default_factory=list)


class RequirementMutationData(BaseModel):
    requirement_id: int
    requirement_no: str | None = None
    status: str
    version: int
    current_handler: CurrentHandlerData | None = None
    completed_at: datetime | None = None


class FieldsSaveData(BaseModel):
    requirement_id: int
    status: str
    version: int
    missing_fields: list[str]
    next_missing_field: str | None = None
    fields_complete: bool


class RequirementListItem(BaseModel):
    requirement_id: int
    requirement_no: str
    device_name: str | None
    status: str
    current_handler_name: str | None


class RequirementListData(BaseModel):
    items: list[RequirementListItem]
    page: int
    page_size: int
    total: int


class RequirementDetailData(BaseModel):
    requirement_id: int
    requirement_no: str
    status: str
    version: int
    building: dict[str, Any]
    current_handler: dict[str, Any] | None
    initiator: dict[str, Any]
    applicant_fields: dict[str, Any]
    review_records: list[dict[str, Any]]
    purchase_execution: dict[str, Any] | None
    warehouse_receipt: dict[str, Any] | None
    missing_fields: list[str]
    allowed_actions: list[str]


class RequirementListQuery(BaseModel):
    view: Literal[
        "CREATED_BY_ME",
        "PENDING_FOR_ME",
        "PROCESSED_BY_ME",
        "BUILDING_SCOPE",
        "ADMIN_SCOPE",
    ]
    status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PurchaseFieldsValidation(BaseModel):
    quantity: int = Field(gt=0)
    unit_price: Decimal
    supplied_total: Decimal | None

    @model_validator(mode="after")
    def validate_total(self) -> "PurchaseFieldsValidation":
        calculated = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        if self.supplied_total is not None and self.supplied_total != calculated:
            raise ValueError("总价与数量乘以单价不一致")
        return self
