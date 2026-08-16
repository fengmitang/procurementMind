from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.schemas.procurement import DeviceType


class BackendIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_type: str = Field(min_length=1, max_length=50)
    platform_user_id: str = Field(min_length=1, max_length=150)

    @field_validator("platform_type")
    @classmethod
    def normalize_platform_type(cls, value: str) -> str:
        return value.upper()


class BackendReadinessData(BaseModel):
    status: str
    mysql: str
    redis: str


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


class BuildingData(BaseModel):
    building_id: int
    building_name: str | None


class CurrentHandlerData(BaseModel):
    employee_id: int
    name: str


class ApplicantFieldsData(BaseModel):
    device_profession: DeviceType | None
    device_name: str | None
    brand: str | None
    model: str | None
    quantity: Decimal | None
    unit: str | None
    application_reason: str | None
    applicant_remark: str | None


class ReviewRecordData(BaseModel):
    review_round: int
    review_status: str
    review_result: str | None
    review_opinion: str | None
    proposed_supplier_id: int | None
    proposed_supplier_name: str | None
    supplier_contact_name: str | None
    supplier_contact_info: str | None
    supplier_link: str | None
    estimated_unit_price: Decimal | None
    estimated_total_price: Decimal | None
    need_contract: bool | None
    contract_type: str | None
    payment_method: str | None
    expected_arrival_date: date | None
    warranty_info: str | None
    review_remark: str | None
    reviewed_at: datetime | None


class PurchaseExecutionData(BaseModel):
    supplier_id: int
    supplier_name: str
    supplier_tax_number: str | None
    bank_name: str | None
    bank_account: str | None
    registered_address: str | None
    contract_contact_info: str | None
    actual_unit_price: Decimal
    actual_total_price: Decimal
    tax_rate: Decimal | None
    purchased_at: datetime
    purchase_remark: str | None


class WarehouseReceiptData(BaseModel):
    warehouse_location: str
    received_quantity: Decimal
    receipt_remark: str | None
    received_at: datetime


class RequirementDetailData(BaseModel):
    requirement_id: int
    requirement_no: str
    status: str
    version: int
    building: BuildingData
    current_handler: CurrentHandlerData | None
    applicant_fields: ApplicantFieldsData
    review_records: list[ReviewRecordData]
    purchase_execution: PurchaseExecutionData | None
    warehouse_receipt: WarehouseReceiptData | None
    missing_fields: list[str]
    allowed_actions: list[str]


class TimelineItem(BaseModel):
    log_id: int
    action_type: str
    operator_name: str
    operator_role_name: str
    operator_mobile_masked: str | None
    from_status: str | None
    to_status: str | None
    assigned_to_employee_id: int | None
    assigned_to_name: str | None
    assigned_to_mobile_masked: str | None
    operation_summary: str | None
    operated_at: datetime


class TimelineData(BaseModel):
    items: list[TimelineItem]


class PurchaseRecordItem(BaseModel):
    requirement_id: int
    requirement_no: str
    device_name: str | None
    brand: str | None
    model: str | None
    quantity: Decimal | None
    unit: str | None
    status: str
    supplier_id: int | None
    supplier_name: str | None
    actual_total_price: Decimal | None
    purchased_at: datetime | None
    created_at: datetime
    submitted_at: datetime | None
    reviewed_at: datetime | None
    received_at: datetime | None
    completed_at: datetime | None


class PurchaseRecordListData(BaseModel):
    items: list[PurchaseRecordItem]
    page: int
    page_size: int
    total: int


class ProductRecommendationItem(BaseModel):
    brand: str | None
    model: str | None
    historical_count: int
    last_purchased_at: datetime


class ProductRecommendationData(BaseModel):
    items: list[ProductRecommendationItem]


class PurchaseHistoryItem(BaseModel):
    requirement_id: int
    device_name: str
    brand: str | None
    model: str | None
    quantity: Decimal
    supplier_id: int
    supplier_name: str
    actual_total_price: Decimal
    purchased_at: datetime
    blacklist_status: str


class PurchaseHistoryRecommendationData(BaseModel):
    items: list[PurchaseHistoryItem]


class SupplierRecommendationItem(BaseModel):
    supplier_id: int
    supplier_name: str
    historical_purchase_count: int
    last_purchase_at: datetime
    blacklist_status: str


class SupplierRecommendationData(BaseModel):
    items: list[SupplierRecommendationItem]


class ActiveConversationData(BaseModel):
    conversation_id: int
    status: str
    purchase_request_id: int | None
    redis_state_exists: bool


class MessageCreatedData(BaseModel):
    message_id: int
    created_at: datetime
    duplicate: bool = False


class MessageData(BaseModel):
    message_id: int
    external_message_id: str | None
    sender_type: str
    content: str
    message_data: dict[str, JsonValue] | None = None
    created_at: datetime


class MessageListData(BaseModel):
    items: list[MessageData]
    page: int
    page_size: int
    total: int


class ConversationData(BaseModel):
    conversation_id: int
    external_conversation_id: str | None
    status: str
    title: str
    message_count: int
    started_at: datetime
    last_active_at: datetime


class ConversationListData(BaseModel):
    items: list[ConversationData]
    page: int
    page_size: int
    total: int


class ConversationStatePayload(BaseModel):
    purchase_request_id: int | None = None
    current_action: str = Field(min_length=1, max_length=30)
    collected_data: dict[str, JsonValue] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    awaiting_confirmation: bool = False
    recent_messages: list[dict[str, JsonValue]] = Field(default_factory=list)
    last_recommendations: list[dict[str, JsonValue]] = Field(default_factory=list)


class ConversationStateData(ConversationStatePayload):
    conversation_id: int
    restored_from_snapshot: bool = False


class StateSavedData(BaseModel):
    saved: bool = True
    expires_in_seconds: int


class SnapshotSavedData(BaseModel):
    state_id: int
    saved_at: datetime


class ConversationCompletedData(BaseModel):
    conversation_id: int
    status: str
    redis_state_deleted: bool


class RequirementMutationData(BaseModel):
    requirement_id: int
    requirement_no: str | None = None
    status: str
    version: int
    current_handler: dict[str, JsonValue] | None = None


class FieldsSaveData(BaseModel):
    requirement_id: int
    status: str
    version: int
    missing_fields: list[str]
    fields_complete: bool
