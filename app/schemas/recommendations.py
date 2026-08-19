from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.procurement import DeviceType


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
    quantity: int
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


class ProductHistoryEvidence(BaseModel):
    reference_id: int
    device_profession: DeviceType | None
    device_name: str | None
    brand: str | None
    model: str | None
    purchased_at: datetime


class ProductHistoryEvidenceData(BaseModel):
    items: list[ProductHistoryEvidence]


class SupplierRecommendationEvidence(BaseModel):
    reference_id: int
    supplier_id: int
    supplier_name: str
    supplier_contact_name: str | None
    supplier_contact_info: str | None
    actual_unit_price: Decimal
    contract_type: str | None
    payment_method: str | None
    blacklist_status: str
    blacklist_history_count: int
    purchased_at: datetime


class SupplierRecommendationEvidenceData(BaseModel):
    items: list[SupplierRecommendationEvidence]


class SupplierContractEvidence(BaseModel):
    reference_id: int
    supplier_id: int
    supplier_name: str
    tax_rate: Decimal | None
    contract_contact_info: str | None
    purchased_at: datetime


class AmbiguousSupplier(BaseModel):
    supplier_id: int
    supplier_name: str


class SupplierContractEvidenceData(BaseModel):
    items: list[SupplierContractEvidence]
    ambiguous_suppliers: list[AmbiguousSupplier] = Field(default_factory=list)


class WarehouseRecommendationEvidence(BaseModel):
    reference_id: int
    device_profession: DeviceType | None
    device_name: str | None
    warehouse_location: str
    received_quantity: int
    received_at: datetime


class WarehouseRecommendationEvidenceData(BaseModel):
    items: list[WarehouseRecommendationEvidence]
