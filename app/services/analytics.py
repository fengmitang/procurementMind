import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.repositories.analytics import AnalysisRow, AnalyticsRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.analytics import (
    AggregateMetrics,
    AnalyticsAggregation,
    AnalyticsGroupBy,
    GroupedMetrics,
    PurchaseAnalysisItem,
    PurchaseQueryData,
    PurchaseQueryRequest,
    RatioMetric,
    SupplierPerformanceData,
)

MONEY_QUANT = Decimal("0.01")
RATIO_QUANT = Decimal("0.0001")


class AnalyticsService:
    def __init__(
        self,
        repository: AnalyticsRepository | None = None,
        supplier_repository: SupplierRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository or AnalyticsRepository()
        self.suppliers = supplier_repository or SupplierRepository()
        self.settings = settings or get_settings()

    async def purchase_query(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        payload: PurchaseQueryRequest,
    ) -> PurchaseQueryData:
        created_from, created_to = self._effective_range(
            payload.created_from,
            payload.created_to,
            max_days=366,
        )
        self._validate_building_scope(current_user, payload.building_ids)
        try:
            async with asyncio.timeout(self.settings.analytics_query_timeout_seconds):
                rows = await self.repository.query_rows(
                    session,
                    current_user,
                    payload,
                    created_from=created_from,
                    created_to=created_to,
                    limit=self.settings.analytics_max_scan_rows + 1,
                )
                self._require_scan_limit(rows)
                scanned_rows = len(rows)
                rows, warnings = await self._apply_exclusions(
                    session,
                    rows,
                    payload,
                    datetime.now(),
                )
        except TimeoutError as exc:
            raise AppError("ANALYTICS_QUERY_TIMEOUT", "采购分析查询超时", 504) from exc

        total = len(rows)
        offset = (payload.page - 1) * payload.page_size
        page_rows = rows[offset : offset + payload.page_size]
        effective_query = payload.model_dump(mode="json")
        effective_query.update(
            {
                "created_from": created_from.isoformat(),
                "created_to": created_to.isoformat(),
                "max_scan_rows": self.settings.analytics_max_scan_rows,
                "statistics_basis": "ACTUAL_EXECUTION_ONLY",
                "delay_definition": (
                    "received_date_after_expected_date_or_expected_date_passed_without_receipt"
                ),
            }
        )
        return PurchaseQueryData(
            items=[self._item(row) for row in page_rows],
            summary=self._metrics(rows, set(payload.aggregations)),
            groups=self._groups(rows, payload),
            page=payload.page,
            page_size=payload.page_size,
            total=total,
            scanned_rows=scanned_rows,
            effective_query=effective_query,
            warnings=warnings,
        )

    async def supplier_performance(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        supplier_id: int,
        *,
        created_from: date | None,
        created_to: date | None,
    ) -> SupplierPerformanceData:
        supplier = await self.suppliers.get(session, supplier_id)
        if supplier is None or not supplier.status:
            raise AppError("SUPPLIER_NOT_FOUND", "供应商不存在", 404)
        range_from, range_to = self._effective_range(
            created_from,
            created_to,
            max_days=1095,
        )
        try:
            async with asyncio.timeout(self.settings.analytics_query_timeout_seconds):
                rows = await self.repository.rows_for_risk_or_cases(
                    session,
                    current_user,
                    created_from=range_from,
                    created_to=range_to,
                    limit=self.settings.analytics_max_scan_rows + 1,
                )
                self._require_scan_limit(rows)
                rows = [
                    row
                    for row in rows
                    if row.execution and row.execution.supplier_id == supplier_id
                ]
                blacklist_status, blacklist_count = await self.suppliers.blacklist_summary(
                    session,
                    supplier_id,
                    datetime.now(),
                )
        except TimeoutError as exc:
            raise AppError("ANALYTICS_QUERY_TIMEOUT", "供应商履约统计超时", 504) from exc

        today = datetime.now().date()
        delay_eligible = [row for row in rows if row.expected_arrival_date is not None]
        delayed = [row for row in delay_eligible if self.is_delayed(row, today)]
        receipt_rows = [
            row for row in rows if row.receipt is not None and row.request.quantity is not None
        ]
        abnormal_quantity = [
            row for row in receipt_rows if row.receipt.received_quantity != row.request.quantity
        ]
        delivery_days = [
            Decimal((row.receipt.received_at.date() - row.execution.purchased_at.date()).days)
            for row in rows
            if row.receipt is not None and row.execution is not None
        ]
        building_map = {row.request.building_id: row.building_name for row in rows}
        warnings = []
        if any(row.expected_arrival_date is None for row in rows):
            warnings.append("缺少预计到货日的记录不计入延期率分母")
        return SupplierPerformanceData(
            supplier_id=supplier_id,
            supplier_name=supplier.supplier_name,
            created_from=range_from,
            created_to=range_to,
            historical_purchase_count=len(rows),
            last_cooperation_at=max(
                (row.execution.purchased_at for row in rows if row.execution),
                default=None,
            ),
            average_delivery_days=(
                self._decimal_average(delivery_days, MONEY_QUANT) if delivery_days else None
            ),
            delay=self._ratio(len(delayed), len(delay_eligible)),
            quantity_anomaly=self._ratio(len(abnormal_quantity), len(receipt_rows)),
            current_blacklist_status=blacklist_status,
            blacklist_history_count=blacklist_count,
            building_ids=sorted(building_map),
            building_names=[building_map[key] for key in sorted(building_map)],
            warnings=warnings,
        )

    async def _apply_exclusions(
        self,
        session: AsyncSession,
        rows: list[AnalysisRow],
        payload: PurchaseQueryRequest,
        now: datetime,
    ) -> tuple[list[AnalysisRow], list[str]]:
        warnings: list[str] = []
        if payload.exclude_blacklisted:
            supplier_ids = {row.supplier_id for row in rows if row.supplier_id is not None}
            blacklisted = await self.repository.effective_blacklisted_supplier_ids(
                session,
                supplier_ids,
                now,
            )
            rows = [row for row in rows if row.supplier_id not in blacklisted]
        if payload.exclude_delayed_suppliers:
            delayed_suppliers = {
                row.supplier_id
                for row in rows
                if row.supplier_id is not None and self.is_delayed(row, now.date())
            }
            rows = [row for row in rows if row.supplier_id not in delayed_suppliers]
            warnings.append("延期供应商按本次查询时间范围内的可见记录判定")
        return rows, warnings

    def _require_scan_limit(self, rows: list[AnalysisRow]) -> None:
        if len(rows) > self.settings.analytics_max_scan_rows:
            raise AppError(
                "ANALYTICS_SCAN_LIMIT_EXCEEDED",
                "匹配记录超过安全扫描上限，请缩小日期或筛选范围",
                422,
                details={"max_scan_rows": self.settings.analytics_max_scan_rows},
            )

    def _effective_range(
        self,
        created_from: date | None,
        created_to: date | None,
        *,
        max_days: int,
    ) -> tuple[date, date]:
        end = created_to or datetime.now().date()
        start = created_from or end - timedelta(
            days=min(self.settings.analytics_default_range_days, max_days)
        )
        days = (end - start).days
        if days < 0 or days > max_days:
            raise AppError(
                "ANALYTICS_DATE_RANGE_INVALID",
                f"日期范围必须按先后顺序且不超过 {max_days} 天",
                422,
            )
        return start, end

    @staticmethod
    def _validate_building_scope(current_user: CurrentUser, building_ids: list[int]) -> None:
        if not building_ids or current_user.has_any_role(RoleCode.ADMIN.value):
            return
        if current_user.has_any_role(RoleCode.BUILDING_MANAGER.value) and not set(
            building_ids
        ).issubset(current_user.building_ids):
            raise AppError("BUILDING_NOT_ALLOWED", "查询包含无权访问的楼宇", 403)

    @staticmethod
    def is_delayed(row: AnalysisRow, today: date) -> bool:
        expected = row.expected_arrival_date
        if expected is None:
            return False
        if row.receipt is not None:
            return row.receipt.received_at.date() > expected
        return row.execution is not None and expected < today

    @classmethod
    def _metrics(
        cls,
        rows: list[AnalysisRow],
        aggregations: set[AnalyticsAggregation],
    ) -> AggregateMetrics:
        unit_prices = [row.execution.actual_unit_price for row in rows if row.execution]
        total_amounts = [row.execution.actual_total_price for row in rows if row.execution]
        return AggregateMetrics(
            count=len(rows) if AnalyticsAggregation.COUNT in aggregations else None,
            average_unit_price=(
                cls._decimal_average(unit_prices, MONEY_QUANT)
                if unit_prices and AnalyticsAggregation.AVERAGE_UNIT_PRICE in aggregations
                else None
            ),
            median_unit_price=(
                Decimal(median(unit_prices)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
                if unit_prices and AnalyticsAggregation.MEDIAN_UNIT_PRICE in aggregations
                else None
            ),
            total_amount=(
                sum(total_amounts, Decimal(0)).quantize(MONEY_QUANT)
                if AnalyticsAggregation.TOTAL_AMOUNT in aggregations
                else None
            ),
        )

    @classmethod
    def _groups(
        cls,
        rows: list[AnalysisRow],
        payload: PurchaseQueryRequest,
    ) -> list[GroupedMetrics]:
        if payload.group_by is None:
            return []
        grouped: dict[tuple[str, str], list[AnalysisRow]] = defaultdict(list)
        for row in rows:
            if payload.group_by is AnalyticsGroupBy.BRAND:
                key = label = row.request.brand or "未填写"
            elif payload.group_by is AnalyticsGroupBy.BUILDING:
                key, label = str(row.request.building_id), row.building_name
            elif payload.group_by is AnalyticsGroupBy.SUPPLIER:
                key = str(row.supplier_id) if row.supplier_id is not None else "NONE"
                label = row.supplier_name or "未选择供应商"
            else:
                key = label = row.request.device_name or "未填写"
            grouped[(key, label)].append(row)
        aggregations = set(payload.aggregations)
        return [
            GroupedMetrics(key=key, label=label, metrics=cls._metrics(group, aggregations))
            for (key, label), group in sorted(grouped.items(), key=lambda item: item[0])
        ]

    @staticmethod
    def _item(row: AnalysisRow) -> PurchaseAnalysisItem:
        return PurchaseAnalysisItem(
            requirement_id=row.request.request_id,
            requirement_no=row.request.request_no,
            building_id=row.request.building_id,
            building_name=row.building_name,
            device_profession=row.request.device_profession,
            device_name=row.request.device_name,
            brand=row.request.brand,
            model=row.request.model,
            quantity=row.request.quantity,
            unit=row.request.unit,
            status=row.request.status,
            current_handler_name=row.current_handler_name,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            actual_unit_price=(row.execution.actual_unit_price if row.execution else None),
            actual_total_price=(row.execution.actual_total_price if row.execution else None),
            expected_arrival_date=row.expected_arrival_date,
            purchased_at=row.execution.purchased_at if row.execution else None,
            received_quantity=(row.receipt.received_quantity if row.receipt else None),
            received_at=row.receipt.received_at if row.receipt else None,
            created_at=row.request.created_at,
            completed_at=row.request.completed_at,
        )

    @staticmethod
    def _decimal_average(values: list[Decimal], quant: Decimal) -> Decimal:
        return (sum(values, Decimal(0)) / Decimal(len(values))).quantize(
            quant,
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> RatioMetric:
        return RatioMetric(
            numerator=numerator,
            denominator=denominator,
            ratio=(
                (Decimal(numerator) / Decimal(denominator)).quantize(RATIO_QUANT)
                if denominator
                else None
            ),
        )
