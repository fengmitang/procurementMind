from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.models.identity import Building
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    SupplierBlacklist,
    WarehouseReceipt,
)
from app.repositories.suppliers import effective_blacklist_condition
from app.schemas.analytics import AnalyticsSortBy, PurchaseQueryRequest, SortOrder


@dataclass(frozen=True, slots=True)
class AnalysisRow:
    request: PurchaseRequest
    building_name: str
    execution: PurchaseExecution | None
    receipt: WarehouseReceipt | None
    expected_arrival_date: date | None
    proposed_supplier_id: int | None
    proposed_supplier_name: str | None
    estimated_unit_price: Decimal | None

    @property
    def supplier_id(self) -> int | None:
        return self.execution.supplier_id if self.execution else self.proposed_supplier_id

    @property
    def supplier_name(self) -> str | None:
        return (
            self.execution.supplier_name_snapshot if self.execution else self.proposed_supplier_name
        )


class AnalyticsRepository:
    @staticmethod
    def visibility_condition(current_user: CurrentUser):
        if current_user.has_any_role(RoleCode.ADMIN.value):
            return None
        if current_user.has_any_role(RoleCode.BUILDING_MANAGER.value):
            return PurchaseRequest.building_id.in_(current_user.building_ids)
        return or_(
            PurchaseRequest.applicant_employee_id == current_user.employee_id,
            PurchaseRequest.current_handler_employee_id == current_user.employee_id,
            exists().where(
                PurchaseOperationLog.request_id == PurchaseRequest.request_id,
                PurchaseOperationLog.operator_employee_id == current_user.employee_id,
            ),
        )

    async def query_rows(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        payload: PurchaseQueryRequest,
        *,
        created_from: date,
        created_to: date,
        limit: int,
    ) -> list[AnalysisRow]:
        statement = self._base_statement(current_user).where(
            PurchaseRequest.created_at >= datetime.combine(created_from, time.min),
            PurchaseRequest.created_at < datetime.combine(created_to + timedelta(days=1), time.min),
        )
        statement = self._apply_filters(statement, payload)
        statement = self._apply_sort(statement, payload).limit(limit)
        return self._rows(await session.execute(statement))

    async def visible_row(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        requirement_id: int,
    ) -> AnalysisRow | None:
        result = await session.execute(
            self._base_statement(current_user).where(PurchaseRequest.request_id == requirement_id)
        )
        rows = self._rows(result)
        return rows[0] if rows else None

    async def rows_for_risk_or_cases(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        *,
        created_from: date,
        created_to: date,
        limit: int,
    ) -> list[AnalysisRow]:
        result = await session.execute(
            self._base_statement(current_user)
            .where(
                PurchaseRequest.created_at >= datetime.combine(created_from, time.min),
                PurchaseRequest.created_at
                < datetime.combine(created_to + timedelta(days=1), time.min),
            )
            .order_by(PurchaseRequest.created_at.desc())
            .limit(limit)
        )
        return self._rows(result)

    async def effective_blacklisted_supplier_ids(
        self,
        session: AsyncSession,
        supplier_ids: set[int],
        now: datetime,
    ) -> set[int]:
        if not supplier_ids:
            return set()
        result = await session.scalars(
            select(SupplierBlacklist.supplier_id).where(
                SupplierBlacklist.supplier_id.in_(supplier_ids),
                effective_blacklist_condition(now),
            )
        )
        return set(result.all())

    def _base_statement(self, current_user: CurrentUser) -> Select:
        expected_arrival = (
            select(PurchaseReview.expected_arrival_date)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        proposed_supplier_id = (
            select(PurchaseReview.proposed_supplier_id)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        proposed_supplier_name = (
            select(PurchaseReview.proposed_supplier_name)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        estimated_unit_price = (
            select(PurchaseReview.estimated_unit_price)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        statement = (
            select(
                PurchaseRequest,
                Building.building_name,
                PurchaseExecution,
                WarehouseReceipt,
                expected_arrival,
                proposed_supplier_id,
                proposed_supplier_name,
                estimated_unit_price,
            )
            .join(Building, Building.building_id == PurchaseRequest.building_id)
            .outerjoin(
                PurchaseExecution,
                PurchaseExecution.request_id == PurchaseRequest.request_id,
            )
            .outerjoin(
                WarehouseReceipt,
                WarehouseReceipt.request_id == PurchaseRequest.request_id,
            )
        )
        visibility = self.visibility_condition(current_user)
        return statement.where(visibility) if visibility is not None else statement

    @staticmethod
    def _apply_filters(statement: Select, payload: PurchaseQueryRequest) -> Select:
        proposed_supplier_id = (
            select(PurchaseReview.proposed_supplier_id)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        estimated_unit_price = (
            select(PurchaseReview.estimated_unit_price)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        effective_unit_price = func.coalesce(
            PurchaseExecution.actual_unit_price,
            estimated_unit_price,
        )
        if payload.building_ids:
            statement = statement.where(PurchaseRequest.building_id.in_(payload.building_ids))
        if payload.device_professions:
            statement = statement.where(
                PurchaseRequest.device_profession.in_(payload.device_professions)
            )
        if payload.device_name:
            statement = statement.where(
                PurchaseRequest.device_name.like(f"%{payload.device_name}%")
            )
        if payload.brands:
            statement = statement.where(PurchaseRequest.brand.in_(payload.brands))
        if payload.models:
            statement = statement.where(PurchaseRequest.model.in_(payload.models))
        if payload.supplier_ids:
            statement = statement.where(
                or_(
                    PurchaseExecution.supplier_id.in_(payload.supplier_ids),
                    proposed_supplier_id.in_(payload.supplier_ids),
                )
            )
        if payload.statuses:
            statement = statement.where(PurchaseRequest.status.in_(payload.statuses))
        if payload.min_unit_price is not None:
            statement = statement.where(effective_unit_price >= payload.min_unit_price)
        if payload.max_unit_price is not None:
            statement = statement.where(effective_unit_price <= payload.max_unit_price)
        if payload.min_total_price is not None:
            statement = statement.where(
                PurchaseExecution.actual_total_price >= payload.min_total_price
            )
        if payload.max_total_price is not None:
            statement = statement.where(
                PurchaseExecution.actual_total_price <= payload.max_total_price
            )
        return statement

    @staticmethod
    def _apply_sort(statement: Select, payload: PurchaseQueryRequest) -> Select:
        estimated_unit_price = (
            select(PurchaseReview.estimated_unit_price)
            .where(PurchaseReview.request_id == PurchaseRequest.request_id)
            .order_by(PurchaseReview.review_round.desc())
            .limit(1)
            .correlate(PurchaseRequest)
            .scalar_subquery()
        )
        sort_columns = {
            AnalyticsSortBy.CREATED_AT: PurchaseRequest.created_at,
            AnalyticsSortBy.UNIT_PRICE: func.coalesce(
                PurchaseExecution.actual_unit_price,
                estimated_unit_price,
            ),
            AnalyticsSortBy.TOTAL_AMOUNT: PurchaseExecution.actual_total_price,
            AnalyticsSortBy.QUANTITY: PurchaseRequest.quantity,
        }
        column = sort_columns[payload.sort_by]
        ordered = column.asc() if payload.sort_order is SortOrder.ASC else column.desc()
        return statement.order_by(ordered, PurchaseRequest.request_id.desc())

    @staticmethod
    def _rows(result) -> list[AnalysisRow]:
        return [
            AnalysisRow(
                request=row[0],
                building_name=row[1],
                execution=row[2],
                receipt=row[3],
                expected_arrival_date=row[4],
                proposed_supplier_id=row[5],
                proposed_supplier_name=row[6],
                estimated_unit_price=row[7],
            )
            for row in result.all()
        ]
