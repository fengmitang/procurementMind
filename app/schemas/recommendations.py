from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


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
