from datetime import datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.repositories.procurement import ProcurementRepository
from app.repositories.recommendations import RecommendationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.recommendations import (
    AmbiguousSupplier,
    ProductHistoryEvidence,
    ProductHistoryEvidenceData,
    ProductRecommendationData,
    ProductRecommendationItem,
    PurchaseHistoryItem,
    PurchaseHistoryRecommendationData,
    SupplierContractEvidence,
    SupplierContractEvidenceData,
    SupplierRecommendationData,
    SupplierRecommendationEvidence,
    SupplierRecommendationEvidenceData,
    SupplierRecommendationItem,
    WarehouseRecommendationEvidence,
    WarehouseRecommendationEvidenceData,
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

    async def product_evidence(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        **filters,
    ) -> ProductHistoryEvidenceData:
        require_any_role(
            current_user,
            RoleCode.APPLICANT.value,
            RoleCode.BUILDING_MANAGER.value,
            RoleCode.PURCHASER.value,
            RoleCode.ADMIN.value,
        )
        rows = await self.repository.product_evidence(
            session, **self._datetime_filters(filters, "purchased")
        )
        return ProductHistoryEvidenceData(
            items=[
                ProductHistoryEvidence(
                    reference_id=request.request_id,
                    device_profession=request.device_profession,
                    device_name=request.device_name,
                    brand=request.brand,
                    model=request.model,
                    purchased_at=execution.purchased_at,
                )
                for request, execution in rows
            ]
        )

    async def supplier_evidence(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        **filters,
    ) -> SupplierRecommendationEvidenceData:
        require_any_role(current_user, RoleCode.BUILDING_MANAGER.value, RoleCode.ADMIN.value)
        building_ids = (
            None
            if current_user.has_any_role(RoleCode.ADMIN.value)
            else set(current_user.building_ids)
        )
        rows = await self.repository.supplier_evidence(
            session,
            building_ids=building_ids,
            **self._datetime_filters(filters, "purchased"),
        )
        request_ids = {request.request_id for request, _ in rows}
        supplier_ids = {execution.supplier_id for _, execution in rows}
        reviews = await self.repository.latest_completed_reviews(session, request_ids)
        blacklist = await self.repository.supplier_blacklist_summaries(
            session, supplier_ids, datetime.now()
        )
        suppliers = await self.repository.suppliers_by_ids(session, supplier_ids)
        items = []
        for request, execution in rows:
            review = reviews.get(request.request_id)
            supplier = suppliers.get(execution.supplier_id)
            status, history_count = blacklist.get(execution.supplier_id, ("NORMAL", 0))
            contact_info = (
                review.supplier_contact_info
                if review and review.supplier_contact_info
                else supplier.contract_contact_info
                if supplier
                else None
            )
            items.append(
                SupplierRecommendationEvidence(
                    reference_id=request.request_id,
                    supplier_id=execution.supplier_id,
                    supplier_name=execution.supplier_name_snapshot,
                    supplier_contact_name=(review.supplier_contact_name if review else None),
                    supplier_contact_info=contact_info,
                    actual_unit_price=execution.actual_unit_price,
                    contract_type=review.contract_type if review else None,
                    payment_method=review.payment_method if review else None,
                    blacklist_status=status,
                    blacklist_history_count=history_count,
                    purchased_at=execution.purchased_at,
                )
            )
        return SupplierRecommendationEvidenceData(items=items)

    async def supplier_contract_evidence(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        **filters,
    ) -> SupplierContractEvidenceData:
        require_any_role(current_user, RoleCode.PURCHASER.value, RoleCode.ADMIN.value)
        supplier_id = filters.get("supplier_id")
        supplier_name = filters.get("supplier_name")
        if supplier_id is None and supplier_name:
            matches = await self.repository.matching_suppliers(session, supplier_name)
            if len(matches) > 1:
                return SupplierContractEvidenceData(
                    items=[],
                    ambiguous_suppliers=[
                        AmbiguousSupplier(
                            supplier_id=item.supplier_id, supplier_name=item.supplier_name
                        )
                        for item in matches
                    ],
                )
            if len(matches) == 1:
                filters["supplier_id"] = matches[0].supplier_id
                filters["supplier_name"] = None
        rows = await self.repository.supplier_contract_evidence(
            session, **self._datetime_filters(filters, "purchased")
        )
        return SupplierContractEvidenceData(
            items=[
                SupplierContractEvidence(
                    reference_id=execution.request_id,
                    supplier_id=execution.supplier_id,
                    supplier_name=execution.supplier_name_snapshot,
                    tax_rate=execution.tax_rate,
                    contract_contact_info=execution.contract_contact_info_snapshot,
                    purchased_at=execution.purchased_at,
                )
                for (execution,) in rows
            ]
        )

    async def warehouse_evidence(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        **filters,
    ) -> WarehouseRecommendationEvidenceData:
        require_any_role(
            current_user, RoleCode.WAREHOUSE_MANAGER.value, RoleCode.ADMIN.value
        )
        rows = await self.repository.warehouse_evidence(
            session, **self._datetime_filters(filters, "received")
        )
        return WarehouseRecommendationEvidenceData(
            items=[
                WarehouseRecommendationEvidence(
                    reference_id=request.request_id,
                    device_profession=request.device_profession,
                    device_name=request.device_name,
                    warehouse_location=receipt.warehouse_location,
                    received_quantity=receipt.received_quantity,
                    received_at=receipt.received_at,
                )
                for request, receipt in rows
            ]
        )

    @staticmethod
    def _datetime_filters(filters: dict, prefix: str) -> dict:
        values = dict(filters)
        start = values.pop(f"{prefix}_from", None)
        end = values.pop(f"{prefix}_to", None)
        values[f"{prefix}_from"] = datetime.combine(start, time.min) if start else None
        values[f"{prefix}_to"] = datetime.combine(end, time.max) if end else None
        return values

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
