from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import PurchaseStatus
from app.schemas.procurement import DeviceType

PositiveId = Annotated[int, Field(gt=0)]
BrandText = Annotated[str, Field(min_length=1, max_length=100)]
ModelText = Annotated[str, Field(min_length=1, max_length=150)]


class AnalyticsAggregation(StrEnum):
    COUNT = "COUNT"
    AVERAGE_UNIT_PRICE = "AVERAGE_UNIT_PRICE"
    MEDIAN_UNIT_PRICE = "MEDIAN_UNIT_PRICE"
    TOTAL_AMOUNT = "TOTAL_AMOUNT"


class AnalyticsGroupBy(StrEnum):
    BRAND = "BRAND"
    BUILDING = "BUILDING"
    SUPPLIER = "SUPPLIER"
    DEVICE_NAME = "DEVICE_NAME"
    STATUS = "STATUS"
    MONTH = "MONTH"


class AnalyticsSortBy(StrEnum):
    CREATED_AT = "CREATED_AT"
    UNIT_PRICE = "UNIT_PRICE"
    TOTAL_AMOUNT = "TOTAL_AMOUNT"
    QUANTITY = "QUANTITY"


class SortOrder(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class PurchaseQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_from: date | None = None
    created_to: date | None = None
    created_by_me: bool = False
    building_ids: list[PositiveId] = Field(default_factory=list, max_length=50)
    device_professions: list[DeviceType] = Field(default_factory=list, max_length=20)
    device_name: str | None = Field(default=None, min_length=1, max_length=200)
    device_names: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    brands: list[BrandText] = Field(default_factory=list, max_length=50)
    models: list[ModelText] = Field(default_factory=list, max_length=50)
    supplier_ids: list[PositiveId] = Field(default_factory=list, max_length=50)
    statuses: list[PurchaseStatus] = Field(default_factory=list, max_length=20)
    min_unit_price: Decimal | None = Field(default=None, ge=0)
    max_unit_price: Decimal | None = Field(default=None, ge=0)
    min_total_price: Decimal | None = Field(default=None, ge=0)
    max_total_price: Decimal | None = Field(default=None, ge=0)
    exclude_blacklisted: bool = False
    exclude_delayed_suppliers: bool = False
    group_by: AnalyticsGroupBy | None = None
    aggregations: list[AnalyticsAggregation] = Field(
        default_factory=lambda: list(AnalyticsAggregation),
        min_length=1,
        max_length=4,
    )
    sort_by: AnalyticsSortBy = AnalyticsSortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_ranges(self) -> "PurchaseQueryRequest":
        if self.created_from and self.created_to:
            days = (self.created_to - self.created_from).days
            if days < 0 or days > 366:
                raise ValueError("查询日期必须按先后顺序且范围不超过 366 天")
        for minimum, maximum, name in (
            (self.min_unit_price, self.max_unit_price, "unit_price"),
            (self.min_total_price, self.max_total_price, "total_price"),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"{name} 最小值不能大于最大值")
        for values, name in (
            (self.building_ids, "building_ids"),
            (self.device_professions, "device_professions"),
            (self.device_names, "device_names"),
            (self.brands, "brands"),
            (self.models, "models"),
            (self.supplier_ids, "supplier_ids"),
            (self.statuses, "statuses"),
            (self.aggregations, "aggregations"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} 不允许重复值")
        return self


class PurchaseAnalysisItem(BaseModel):
    requirement_id: int
    requirement_no: str
    building_id: int
    building_name: str
    device_profession: str | None
    device_name: str | None
    brand: str | None
    model: str | None
    quantity: Decimal | None
    unit: str | None
    status: str
    current_handler_name: str | None
    supplier_id: int | None
    supplier_name: str | None
    actual_unit_price: Decimal | None
    actual_total_price: Decimal | None
    expected_arrival_date: date | None
    purchased_at: datetime | None
    received_quantity: Decimal | None
    received_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


class AggregateMetrics(BaseModel):
    count: int | None = None
    average_unit_price: Decimal | None = None
    median_unit_price: Decimal | None = None
    total_amount: Decimal | None = None


class GroupedMetrics(BaseModel):
    key: str
    label: str
    metrics: AggregateMetrics


class PurchaseQueryData(BaseModel):
    items: list[PurchaseAnalysisItem]
    summary: AggregateMetrics
    groups: list[GroupedMetrics]
    page: int
    page_size: int
    total: int
    scanned_rows: int
    effective_query: dict[str, JsonValue]
    warnings: list[str] = Field(default_factory=list)


class RiskLevel(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskSignal(BaseModel):
    risk_code: str
    risk_type: str
    risk_level: RiskLevel
    matched: bool
    facts: dict[str, JsonValue]
    metrics: dict[str, JsonValue]
    related_record_ids: list[int]
    threshold: dict[str, JsonValue]
    time_range: dict[str, JsonValue]


class RequirementRiskData(BaseModel):
    requirement_id: int
    evaluated_at: datetime
    signals: list[RiskSignal]
    matched_count: int
    scanned_rows: int


class RatioMetric(BaseModel):
    numerator: int
    denominator: int
    ratio: Decimal | None


class SupplierPerformanceData(BaseModel):
    supplier_id: int
    supplier_name: str
    created_from: date
    created_to: date
    historical_purchase_count: int
    last_cooperation_at: datetime | None
    average_delivery_days: Decimal | None
    delay: RatioMetric
    quantity_anomaly: RatioMetric
    current_blacklist_status: str
    blacklist_history_count: int
    building_ids: list[int]
    building_names: list[str]
    warnings: list[str] = Field(default_factory=list)


class SimilarCaseItem(BaseModel):
    requirement_id: int
    requirement_no: str
    status: str
    similarity_score: Decimal
    matched_factors: list[str]
    device_profession: str | None
    device_name: str | None
    brand: str | None
    model: str | None
    quantity: Decimal | None
    building_id: int
    building_name: str
    supplier_id: int | None
    supplier_name: str | None
    actual_total_price: Decimal | None
    completed_at: datetime | None


class SimilarCasesData(BaseModel):
    requirement_id: int
    algorithm: str
    items: list[SimilarCaseItem]
    scanned_rows: int
