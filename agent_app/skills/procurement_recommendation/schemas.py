from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from app.schemas.procurement import DeviceType


class RecommendationProfileId(StrEnum):
    REQUESTER = "REQUESTER"
    BUILDING_MANAGER = "BUILDING_MANAGER"
    PURCHASER = "PURCHASER"
    WAREHOUSE_MANAGER = "WAREHOUSE_MANAGER"


class RecommendationType(StrEnum):
    BRAND_MODEL = "BRAND_MODEL"
    SUPPLIER = "SUPPLIER"
    PURCHASER_CONTRACT = "PURCHASER_CONTRACT"
    WAREHOUSE = "WAREHOUSE"


class RecommendationTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None
    description: str | None = None


class RecommendationQueryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: int | None = None
    device_profession: DeviceType | None = None
    device_name: str | None = None
    resolved_device_names: list[str] = Field(default_factory=list, max_length=5)
    brand: str | None = None
    model: str | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None


class RequesterCandidateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["BRAND_MODEL"] = "BRAND_MODEL"
    brand: str | None = None
    model: str | None = None


class SupplierCandidateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["SUPPLIER"] = "SUPPLIER"
    supplier_id: int
    supplier_name: str
    supplier_contact_name: str | None = None
    supplier_contact_info: str | None = None
    reference_unit_price: Decimal | None = None
    contract_type: str | None = None
    payment_method: str | None = None
    blacklist_status: str
    blacklist_history_count: int = 0


class PurchaserCandidateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["PURCHASER_CONTRACT"] = "PURCHASER_CONTRACT"
    supplier_id: int
    supplier_name: str
    tax_rate: Decimal | None = None
    contract_contact_info: str | None = None


class WarehouseCandidateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["WAREHOUSE"] = "WAREHOUSE"
    warehouse_location: str


CandidateFields = Annotated[
    RequesterCandidateFields
    | SupplierCandidateFields
    | PurchaserCandidateFields
    | WarehouseCandidateFields,
    Field(discriminator="kind"),
]


class RecommendationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    title: str
    fields: CandidateFields
    evidence_count: int = Field(ge=1)
    last_seen_at: datetime
    best_retrieval_stage: int = Field(ge=1)
    evidence_refs: list[int] = Field(max_length=20)
    warnings: list[str] = Field(default_factory=list)


class ProductEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["PRODUCT"] = "PRODUCT"
    device_profession: DeviceType | None = None
    device_name: str | None = None
    brand: str | None = None
    model: str | None = None


class SupplierEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["SUPPLIER"] = "SUPPLIER"
    supplier_id: int
    supplier_name: str
    supplier_contact_name: str | None = None
    supplier_contact_info: str | None = None
    actual_unit_price: Decimal | None = None
    contract_type: str | None = None
    payment_method: str | None = None
    blacklist_status: str
    blacklist_history_count: int = 0


class ContractEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["CONTRACT"] = "CONTRACT"
    supplier_id: int
    supplier_name: str
    tax_rate: Decimal | None = None
    contract_contact_info: str | None = None


class WarehouseEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["WAREHOUSE"] = "WAREHOUSE"
    device_profession: DeviceType | None = None
    device_name: str | None = None
    warehouse_location: str
    received_quantity: int


EvidenceData = Annotated[
    ProductEvidenceData | SupplierEvidenceData | ContractEvidenceData | WarehouseEvidenceData,
    Field(discriminator="kind"),
]


class RecommendationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: int
    source_tool: str
    occurred_at: datetime
    retrieval_stage: int = Field(ge=1)
    match_basis: list[str]
    data: EvidenceData


class RecommendationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: Literal["procurement_recommendation"] = "procurement_recommendation"
    skill_version: Literal["1.0"] = "1.0"
    profile: RecommendationProfileId | None = None
    recommendation_type: RecommendationType | None = None
    time_range: RecommendationTimeRange
    query_context: RecommendationQueryContext
    candidates: list[RecommendationCandidate] = Field(default_factory=list, max_length=5)
    evidence: list[RecommendationEvidence] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list)
    retrieval_stages_used: list[int] = Field(default_factory=list)
    no_result_reason: str | None = None
    clarification_required: bool = False
    clarification_message: str | None = None

    @model_serializer(mode="wrap")
    def serialize_for_profile(self, handler: SerializerFunctionWrapHandler) -> dict:
        data = handler(self)
        if self.profile is RecommendationProfileId.REQUESTER:
            query_context = data.get("query_context")
            if isinstance(query_context, dict):
                query_context.pop("supplier_id", None)
                query_context.pop("supplier_name", None)
        return data

    def compact_state(self) -> dict:
        query_context = self.query_context.model_dump(mode="json")
        if self.profile is RecommendationProfileId.REQUESTER:
            query_context.pop("supplier_id", None)
            query_context.pop("supplier_name", None)
        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "profile": self.profile.value if self.profile else None,
            "recommendation_type": (
                self.recommendation_type.value if self.recommendation_type else None
            ),
            "time_range": self.time_range.model_dump(mode="json"),
            "query_context": query_context,
            "candidates": [item.model_dump(mode="json") for item in self.candidates],
            "reference_ids": [item.reference_id for item in self.evidence],
            "warnings": self.warnings,
        }


class SkillToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict
    success: bool
    code: str
    source: str
    trace_id: str
    duration_ms: int = Field(ge=0)
    data: dict | None = None


class RecommendationSkillResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output: RecommendationOutput
    tool_calls: list[SkillToolCall] = Field(default_factory=list)
