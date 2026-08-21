from dataclasses import dataclass

from agent_app.skills.procurement_recommendation.schemas import (
    RecommendationProfileId,
    RecommendationType,
)


@dataclass(frozen=True, slots=True)
class RecommendationProfile:
    profile_id: RecommendationProfileId
    required_role: str
    recommendation_type: RecommendationType
    retrieval_stages: tuple[tuple[str, ...], ...]
    candidate_key: tuple[str, ...]
    time_field: str
    output_fields: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    evidence_limit: int = 20
    candidate_limit: int = 5


PROFILES = {
    RecommendationProfileId.REQUESTER: RecommendationProfile(
        RecommendationProfileId.REQUESTER,
        "APPLICANT",
        RecommendationType.BRAND_MODEL,
        (("device_profession", "device_names"), ("device_names",), ("device_profession",)),
        ("brand", "model"),
        "purchased_at",
        ("brand", "model"),
        ("search_product_history_evidence",),
    ),
    RecommendationProfileId.BUILDING_MANAGER: RecommendationProfile(
        RecommendationProfileId.BUILDING_MANAGER,
        "BUILDING_MANAGER",
        RecommendationType.SUPPLIER,
        (
            ("device_names", "brand", "model"),
            ("device_names", "brand"),
            ("device_names",),
            ("device_profession",),
        ),
        ("supplier_id",),
        "purchased_at",
        (
            "supplier_id", "supplier_name", "supplier_contact_name",
            "supplier_contact_info", "reference_unit_price", "contract_type",
            "payment_method", "blacklist_status", "blacklist_history_count",
        ),
        ("search_supplier_recommendation_evidence",),
    ),
    RecommendationProfileId.PURCHASER: RecommendationProfile(
        RecommendationProfileId.PURCHASER,
        "PURCHASER",
        RecommendationType.PURCHASER_CONTRACT,
        (("supplier_id",), ("supplier_name",), ()),
        ("tax_rate", "contract_contact_info"),
        "purchased_at",
        ("tax_rate", "contract_contact_info"),
        ("search_supplier_contract_evidence",),
    ),
    RecommendationProfileId.WAREHOUSE_MANAGER: RecommendationProfile(
        RecommendationProfileId.WAREHOUSE_MANAGER,
        "WAREHOUSE_MANAGER",
        RecommendationType.WAREHOUSE,
        (("device_profession", "device_names"), ("device_names",), ("device_profession",)),
        ("warehouse_location",),
        "received_at",
        ("warehouse_location",),
        ("search_warehouse_evidence",),
    ),
}

PROFILE_BY_TYPE = {profile.recommendation_type: profile for profile in PROFILES.values()}
