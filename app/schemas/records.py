from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PurchaseRecordItem(BaseModel):
    requirement_id: int
    requirement_no: str
    device_name: str | None
    brand: str | None
    model: str | None
    quantity: int | None
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


class TimelineContactData(BaseModel):
    employee_name: str
    mobile: str | None
