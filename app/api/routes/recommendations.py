from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.procurement import DeviceType
from app.schemas.recommendations import (
    ProductHistoryEvidenceData,
    ProductRecommendationData,
    PurchaseHistoryRecommendationData,
    SupplierContractEvidenceData,
    SupplierRecommendationData,
    SupplierRecommendationEvidenceData,
    WarehouseRecommendationEvidenceData,
)
from app.services.recommendations import RecommendationService

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


@router.get("/products", response_model=ApiResponse[ProductRecommendationData])
async def recommend_products(
    current_user: CurrentUserDependency,
    session: DbSession,
    device_name: str = Query(min_length=1),
    device_profession: Annotated[DeviceType | None, Query()] = None,
    keyword: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=30),
) -> ApiResponse[ProductRecommendationData]:
    data = await RecommendationService().products(
        session,
        current_user,
        device_profession=device_profession,
        device_name=device_name,
        keyword=keyword,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/purchase-history",
    response_model=ApiResponse[PurchaseHistoryRecommendationData],
)
async def recommend_purchase_history(
    current_user: CurrentUserDependency,
    session: DbSession,
    requirement_id: int = Query(),
    limit: int = Query(default=10, ge=1, le=30),
) -> ApiResponse[PurchaseHistoryRecommendationData]:
    data = await RecommendationService().purchase_history(
        session,
        current_user,
        requirement_id=requirement_id,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get("/suppliers", response_model=ApiResponse[SupplierRecommendationData])
async def recommend_suppliers(
    current_user: CurrentUserDependency,
    session: DbSession,
    requirement_id: int = Query(),
    limit: int = Query(default=10, ge=1, le=30),
) -> ApiResponse[SupplierRecommendationData]:
    data = await RecommendationService().suppliers_for_request(
        session,
        current_user,
        requirement_id=requirement_id,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get("/evidence/products", response_model=ApiResponse[ProductHistoryEvidenceData])
async def search_product_history_evidence(
    current_user: CurrentUserDependency,
    session: DbSession,
    device_profession: Annotated[DeviceType | None, Query()] = None,
    device_names: Annotated[list[str] | None, Query()] = None,
    purchased_from: Annotated[date | None, Query()] = None,
    purchased_to: Annotated[date | None, Query()] = None,
    limit: int = Query(default=20, ge=1, le=20),
) -> ApiResponse[ProductHistoryEvidenceData]:
    data = await RecommendationService().product_evidence(
        session,
        current_user,
        device_profession=device_profession,
        device_names=device_names or [],
        purchased_from=purchased_from,
        purchased_to=purchased_to,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/evidence/suppliers", response_model=ApiResponse[SupplierRecommendationEvidenceData]
)
async def search_supplier_recommendation_evidence(
    current_user: CurrentUserDependency,
    session: DbSession,
    device_profession: Annotated[DeviceType | None, Query()] = None,
    device_names: Annotated[list[str] | None, Query()] = None,
    brand: str | None = Query(default=None, max_length=100),
    model: str | None = Query(default=None, max_length=150),
    purchased_from: Annotated[date | None, Query()] = None,
    purchased_to: Annotated[date | None, Query()] = None,
    limit: int = Query(default=20, ge=1, le=20),
) -> ApiResponse[SupplierRecommendationEvidenceData]:
    data = await RecommendationService().supplier_evidence(
        session,
        current_user,
        device_profession=device_profession,
        device_names=device_names or [],
        brand=brand,
        model=model,
        purchased_from=purchased_from,
        purchased_to=purchased_to,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/evidence/supplier-contracts", response_model=ApiResponse[SupplierContractEvidenceData]
)
async def search_supplier_contract_evidence(
    current_user: CurrentUserDependency,
    session: DbSession,
    supplier_id: int | None = Query(default=None, gt=0),
    supplier_name: str | None = Query(default=None, max_length=200),
    purchased_from: Annotated[date | None, Query()] = None,
    purchased_to: Annotated[date | None, Query()] = None,
    limit: int = Query(default=20, ge=1, le=20),
) -> ApiResponse[SupplierContractEvidenceData]:
    data = await RecommendationService().supplier_contract_evidence(
        session,
        current_user,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        purchased_from=purchased_from,
        purchased_to=purchased_to,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/evidence/warehouses", response_model=ApiResponse[WarehouseRecommendationEvidenceData]
)
async def search_warehouse_evidence(
    current_user: CurrentUserDependency,
    session: DbSession,
    device_profession: Annotated[DeviceType | None, Query()] = None,
    device_names: Annotated[list[str] | None, Query()] = None,
    received_from: Annotated[date | None, Query()] = None,
    received_to: Annotated[date | None, Query()] = None,
    limit: int = Query(default=20, ge=1, le=20),
) -> ApiResponse[WarehouseRecommendationEvidenceData]:
    data = await RecommendationService().warehouse_evidence(
        session,
        current_user,
        device_profession=device_profession,
        device_names=device_names or [],
        received_from=received_from,
        received_to=received_to,
        limit=limit,
    )
    return ApiResponse(data=data)
