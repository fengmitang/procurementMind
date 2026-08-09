from datetime import date

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.analytics import (
    PurchaseQueryData,
    PurchaseQueryRequest,
    RequirementRiskData,
    SimilarCasesData,
    SupplierPerformanceData,
)
from app.services.analytics import AnalyticsService
from app.services.risk_analysis import RiskAnalysisService

router = APIRouter(tags=["analytics"])


@router.post(
    "/api/v1/analytics/purchase-query",
    response_model=ApiResponse[PurchaseQueryData],
)
async def purchase_query(
    payload: PurchaseQueryRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[PurchaseQueryData]:
    data = await AnalyticsService().purchase_query(session, current_user, payload)
    return ApiResponse(data=data)


@router.get(
    "/api/v1/requirements/{requirement_id}/risk-signals",
    response_model=ApiResponse[RequirementRiskData],
)
async def requirement_risk_signals(
    requirement_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[RequirementRiskData]:
    data = await RiskAnalysisService().requirement_risks(
        session,
        current_user,
        requirement_id,
    )
    return ApiResponse(data=data)


@router.get(
    "/api/v1/requirements/{requirement_id}/similar-cases",
    response_model=ApiResponse[SimilarCasesData],
)
async def requirement_similar_cases(
    requirement_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
    limit: int = Query(default=10, ge=1, le=20),
) -> ApiResponse[SimilarCasesData]:
    data = await RiskAnalysisService().similar_cases(
        session,
        current_user,
        requirement_id,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/api/v1/suppliers/{supplier_id}/performance",
    response_model=ApiResponse[SupplierPerformanceData],
)
async def supplier_performance(
    supplier_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
    created_from: date | None = None,
    created_to: date | None = None,
) -> ApiResponse[SupplierPerformanceData]:
    data = await AnalyticsService().supplier_performance(
        session,
        current_user,
        supplier_id,
        created_from=created_from,
        created_to=created_to,
    )
    return ApiResponse(data=data)
