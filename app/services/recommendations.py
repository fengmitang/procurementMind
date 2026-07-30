from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.repositories.procurement import ProcurementRepository
from app.repositories.recommendations import RecommendationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.recommendations import (
    ProductRecommendationData,
    ProductRecommendationItem,
    PurchaseHistoryItem,
    PurchaseHistoryRecommendationData,
    SupplierRecommendationData,
    SupplierRecommendationItem,
)
from app.services.permissions import require_any_role


class RecommendationService:
    def __init__(
        self,
        repository: RecommendationRepository | None = None,
        procurement_repository: ProcurementRepository | None = None,
        supplier_repository: SupplierRepository | None = None,
    ) -> None:
        self.suppliers = supplier_repository or SupplierRepository()
        self.repository = repository or RecommendationRepository(self.suppliers)
        self.procurement = procurement_repository or ProcurementRepository()

    async def products(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        device_profession: str | None,
        device_name: str,
        keyword: str | None,
        limit: int,
    ) -> ProductRecommendationData:
        require_any_role(
            current_user,
            RoleCode.APPLICANT.value,
            RoleCode.BUILDING_MANAGER.value,
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        rows = await self.repository.products(
            session,
            device_profession=device_profession,
            device_name=device_name,
            keyword=keyword,
            limit=limit,
        )
        return ProductRecommendationData(
            items=[
                ProductRecommendationItem(
                    brand=brand,
                    model=model,
                    historical_count=count,
                    last_purchased_at=last_purchased_at,
                )
                for brand, model, count, last_purchased_at in rows
            ]
        )

    async def purchase_history(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        requirement_id: int,
        limit: int,
    ) -> PurchaseHistoryRecommendationData:
        require_any_role(
            current_user,
            RoleCode.BUILDING_MANAGER.value,
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        current_request = await self._get_visible_request(
            session,
            current_user,
            requirement_id,
        )
        rows = await self.repository.similar_history(
            session,
            current_request,
            limit,
        )
        now = datetime.now()
        items = []
        for request, execution in rows:
            blacklist_status, _ = await self.suppliers.blacklist_summary(
                session,
                execution.supplier_id,
                now,
            )
            items.append(
                PurchaseHistoryItem(
                    requirement_id=request.request_id,
                    device_name=request.device_name or "",
                    brand=request.brand,
                    model=request.model,
                    quantity=request.quantity,
                    supplier_id=execution.supplier_id,
                    supplier_name=execution.supplier_name_snapshot,
                    actual_total_price=execution.actual_total_price,
                    purchased_at=execution.purchased_at,
                    blacklist_status=blacklist_status,
                )
            )
        return PurchaseHistoryRecommendationData(items=items)

    async def suppliers_for_request(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        requirement_id: int,
        limit: int,
    ) -> SupplierRecommendationData:
        require_any_role(
            current_user,
            RoleCode.BUILDING_MANAGER.value,
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        current_request = await self._get_visible_request(
            session,
            current_user,
            requirement_id,
        )
        rows = await self.repository.supplier_history(
            session,
            current_request,
            limit,
        )
        now = datetime.now()
        items = []
        for supplier, purchase_count, last_purchase_at in rows:
            blacklist_status, _ = await self.suppliers.blacklist_summary(
                session,
                supplier.supplier_id,
                now,
            )
            if blacklist_status == "BLACKLISTED":
                continue
            items.append(
                SupplierRecommendationItem(
                    supplier_id=supplier.supplier_id,
                    supplier_name=supplier.supplier_name,
                    historical_purchase_count=purchase_count,
                    last_purchase_at=last_purchase_at,
                    blacklist_status=blacklist_status,
                )
            )
            if len(items) >= limit:
                break
        return SupplierRecommendationData(items=items)

    async def _get_visible_request(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        requirement_id: int,
    ):
        request = await self.procurement.get_request(session, requirement_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)
        visible = await self.procurement.can_view_request(
            session,
            request,
            current_user.employee_id,
            current_user.has_any_role(RoleCode.ADMIN.value),
            current_user.building_ids,
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value),
        )
        if not visible:
            raise AppError("PERMISSION_DENIED", "无权查看该采购申请推荐", 403)
        return request
