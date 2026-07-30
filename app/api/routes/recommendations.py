from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.recommendations import (
    ProductRecommendationData,
    PurchaseHistoryRecommendationData,
    SupplierRecommendationData,
)
from app.services.recommendations import RecommendationService

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


@router.get("/products", response_model=ApiResponse[ProductRecommendationData])
async def recommend_products(
    current_user: CurrentUserDependency,
    session: DbSession,
    device_name: str = Query(min_length=1),
    device_profession: str | None = Query(default=None),
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
