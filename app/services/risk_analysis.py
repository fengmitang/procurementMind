import asyncio
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.repositories.analytics import AnalysisRow, AnalyticsRepository
from app.repositories.procurement import ProcurementRepository
from app.schemas.analytics import (
    RequirementRiskData,
    RiskLevel,
    RiskSignal,
    SimilarCaseItem,
    SimilarCasesData,
)


class RiskAnalysisService:
    def __init__(
        self,
        repository: AnalyticsRepository | None = None,
        procurement_repository: ProcurementRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository or AnalyticsRepository()
        self.procurement = procurement_repository or ProcurementRepository()
        self.settings = settings or get_settings()

    async def requirement_risks(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        requirement_id: int,
    ) -> RequirementRiskData:
        now = datetime.now()
        current = await self._visible_row(session, current_user, requirement_id)
        try:
            async with asyncio.timeout(self.settings.analytics_query_timeout_seconds):
                candidates = await self.repository.rows_for_risk_or_cases(
                    session,
                    current_user,
                    created_from=now.date() - timedelta(days=365),
                    created_to=now.date(),
                    limit=self.settings.analytics_max_scan_rows + 1,
                )
                self._require_scan_limit(candidates)
                supplier_ids = {current.supplier_id} if current.supplier_id is not None else set()
                blacklisted = await self.repository.effective_blacklisted_supplier_ids(
                    session,
                    supplier_ids,
                    now,
                )
        except TimeoutError as exc:
            raise AppError("RISK_ANALYSIS_TIMEOUT", "采购风险分析超时", 504) from exc

        signals = self._evaluate(current, candidates, blacklisted, now)
        return RequirementRiskData(
            requirement_id=requirement_id,
            evaluated_at=now,
            signals=signals,
            matched_count=sum(signal.matched for signal in signals),
            scanned_rows=len(candidates),
        )

    async def similar_cases(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        requirement_id: int,
        *,
        limit: int,
    ) -> SimilarCasesData:
        now = datetime.now()
        current = await self._visible_row(session, current_user, requirement_id)
        try:
            async with asyncio.timeout(self.settings.analytics_query_timeout_seconds):
                candidates = await self.repository.rows_for_risk_or_cases(
                    session,
                    current_user,
                    created_from=now.date() - timedelta(days=1095),
                    created_to=now.date(),
                    limit=self.settings.analytics_max_scan_rows + 1,
                )
                self._require_scan_limit(candidates)
        except TimeoutError as exc:
            raise AppError("SIMILAR_CASE_QUERY_TIMEOUT", "相似案例查询超时", 504) from exc
        scored = []
        for row in candidates:
            if row.request.request_id == current.request.request_id:
                continue
            score, factors = self.similarity(current, row)
            if score >= Decimal("0.15"):
                scored.append((score, row, factors))
        scored.sort(
            key=lambda item: (item[0], item[1].request.created_at),
            reverse=True,
        )
        return SimilarCasesData(
            requirement_id=requirement_id,
            algorithm="RULE_WEIGHTED_V1",
            items=[self._case_item(score, row, factors) for score, row, factors in scored[:limit]],
            scanned_rows=len(candidates),
        )

    async def _visible_row(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        requirement_id: int,
    ) -> AnalysisRow:
        request = await self.procurement.get_request(session, requirement_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)
        can_view = await self.procurement.can_view_request(
            session,
            request,
            current_user.employee_id,
            current_user.has_any_role(RoleCode.ADMIN.value),
            current_user.building_ids,
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value),
        )
        if not can_view:
            raise AppError("PERMISSION_DENIED", "无权查看该采购申请", 403)
        row = await self.repository.visible_row(session, current_user, requirement_id)
        if row is None:
            raise AppError("PERMISSION_DENIED", "无权分析该采购申请", 403)
        return row

    def _evaluate(
        self,
        current: AnalysisRow,
        candidates: list[AnalysisRow],
        blacklisted: set[int],
        now: datetime,
    ) -> list[RiskSignal]:
        others = [row for row in candidates if row.request.request_id != current.request.request_id]
        similar_device = [row for row in others if self._same_device(current, row)]
        duplicate_since = current.request.created_at.date() - timedelta(
            days=self.settings.risk_duplicate_window_days
        )
        duplicates = [
            row
            for row in similar_device
            if row.request.building_id == current.request.building_id
            and duplicate_since
            <= row.request.created_at.date()
            <= current.request.created_at.date()
        ]
        price_history = [
            row.execution.actual_unit_price
            for row in similar_device
            if row.execution is not None and row.execution.purchased_at >= now - timedelta(days=180)
        ]
        current_price = (
            current.execution.actual_unit_price
            if current.execution is not None
            else current.estimated_unit_price
        )
        median_price = Decimal(median(price_history)) if price_history else None
        price_deviation = (
            (current_price - median_price) / median_price
            if current_price is not None and median_price not in (None, Decimal(0))
            else None
        )
        price_matched = bool(
            price_deviation is not None
            and price_deviation > Decimal(str(self.settings.risk_price_deviation_ratio))
        )
        quantities = [row.request.quantity for row in similar_device if row.request.quantity]
        average_quantity = (
            sum(quantities, Decimal(0)) / Decimal(len(quantities)) if quantities else None
        )
        quantity_ratio = Decimal(str(self.settings.risk_quantity_deviation_ratio))
        quantity_high = bool(
            current.request.quantity is not None
            and average_quantity is not None
            and current.request.quantity > average_quantity * (Decimal(1) + quantity_ratio)
        )
        receipt_variance = (
            current.receipt.received_quantity - current.request.quantity
            if current.receipt is not None and current.request.quantity is not None
            else None
        )
        quantity_matched = quantity_high or receipt_variance not in (None, Decimal(0))
        delayed = self._is_delayed(current, now)
        pending_days = (
            (now.date() - current.execution.purchased_at.date()).days
            if current.execution is not None and current.receipt is None
            else None
        )
        long_pending = bool(
            pending_days is not None and pending_days > self.settings.risk_long_pending_days
        )
        similar_cases = [
            (score, row)
            for row in others
            if (score := self.similarity(current, row)[0]) >= Decimal("0.40")
        ]
        supplier_blacklisted = (
            current.supplier_id is not None and current.supplier_id in blacklisted
        )
        return [
            self._signal(
                "DUPLICATE_APPLICATION",
                "重复申请",
                bool(duplicates),
                facts={"building_id": current.request.building_id},
                metrics={"similar_count": len(duplicates)},
                related=[row.request.request_id for row in duplicates[:20]],
                threshold={"window_days": self.settings.risk_duplicate_window_days},
                start=duplicate_since.isoformat(),
                end=current.request.created_at.date().isoformat(),
            ),
            self._signal(
                "PRICE_DEVIATION",
                "价格异常",
                price_matched,
                facts={"current_unit_price": self._decimal_text(current_price)},
                metrics={
                    "historical_median": self._decimal_text(median_price),
                    "deviation_ratio": self._decimal_text(price_deviation),
                    "sample_count": len(price_history),
                },
                related=[],
                threshold={"above_median_ratio": self.settings.risk_price_deviation_ratio},
                start=(now.date() - timedelta(days=180)).isoformat(),
                end=now.date().isoformat(),
            ),
            self._signal(
                "QUANTITY_DEVIATION",
                "数量异常",
                quantity_matched,
                facts={
                    "requested_quantity": self._decimal_text(current.request.quantity),
                    "receipt_variance": self._decimal_text(receipt_variance),
                },
                metrics={
                    "historical_average_quantity": self._decimal_text(average_quantity),
                    "sample_count": len(quantities),
                },
                related=[],
                threshold={"above_average_ratio": self.settings.risk_quantity_deviation_ratio},
                start=(now.date() - timedelta(days=365)).isoformat(),
                end=now.date().isoformat(),
            ),
            self._signal(
                "SUPPLIER_BLACKLIST",
                "黑名单供应商",
                supplier_blacklisted,
                facts={"supplier_id": current.supplier_id},
                metrics={},
                related=[],
                threshold={"effective_status": "ACTIVE"},
                start=None,
                end=now.date().isoformat(),
                matched_level=RiskLevel.HIGH,
            ),
            self._signal(
                "DELIVERY_DELAY",
                "供应商延期",
                delayed,
                facts={
                    "expected_arrival_date": (
                        current.expected_arrival_date.isoformat()
                        if current.expected_arrival_date
                        else None
                    ),
                    "received_at": (
                        current.receipt.received_at.isoformat() if current.receipt else None
                    ),
                },
                metrics={},
                related=[],
                threshold={"grace_days": 0},
                start=(
                    current.expected_arrival_date.isoformat()
                    if current.expected_arrival_date
                    else None
                ),
                end=now.date().isoformat(),
            ),
            self._signal(
                "LONG_PENDING_RECEIPT",
                "长期未入库",
                long_pending,
                facts={"pending_days": pending_days},
                metrics={},
                related=[],
                threshold={"pending_days": self.settings.risk_long_pending_days},
                start=(
                    current.execution.purchased_at.date().isoformat() if current.execution else None
                ),
                end=now.date().isoformat(),
            ),
            self._signal(
                "SIMILAR_APPLICATION",
                "相似历史申请",
                bool(similar_cases),
                facts={},
                metrics={"similar_count": len(similar_cases)},
                related=[row.request.request_id for _, row in similar_cases[:20]],
                threshold={"similarity_score": "0.40"},
                start=(now.date() - timedelta(days=365)).isoformat(),
                end=now.date().isoformat(),
                matched_level=RiskLevel.LOW,
            ),
        ]

    @staticmethod
    def similarity(current: AnalysisRow, candidate: AnalysisRow) -> tuple[Decimal, list[str]]:
        score = Decimal(0)
        factors = []
        if current.request.device_profession and (
            current.request.device_profession == candidate.request.device_profession
        ):
            score += Decimal("0.25")
            factors.append("device_profession")
        current_name = RiskAnalysisService._normalized(current.request.device_name)
        candidate_name = RiskAnalysisService._normalized(candidate.request.device_name)
        if current_name and current_name == candidate_name:
            score += Decimal("0.30")
            factors.append("device_name_exact")
        elif (
            current_name
            and candidate_name
            and (current_name in candidate_name or candidate_name in current_name)
        ):
            score += Decimal("0.15")
            factors.append("device_name_similar")
        if current.request.brand and current.request.brand == candidate.request.brand:
            score += Decimal("0.15")
            factors.append("brand")
        if current.request.model and current.request.model == candidate.request.model:
            score += Decimal("0.15")
            factors.append("model")
        if current.request.building_id == candidate.request.building_id:
            score += Decimal("0.05")
            factors.append("building")
        if current.request.quantity and candidate.request.quantity:
            larger = max(current.request.quantity, candidate.request.quantity)
            difference_ratio = abs(current.request.quantity - candidate.request.quantity) / larger
            if difference_ratio <= Decimal("0.20"):
                score += Decimal("0.10")
                factors.append("quantity_range")
        return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), factors

    @staticmethod
    def _same_device(current: AnalysisRow, candidate: AnalysisRow) -> bool:
        left = RiskAnalysisService._normalized(current.request.device_name)
        right = RiskAnalysisService._normalized(candidate.request.device_name)
        name_matches = bool(left and right and (left == right or left in right or right in left))
        class_matches = bool(
            current.request.device_profession
            and current.request.device_profession == candidate.request.device_profession
            and current.request.brand
            and current.request.brand == candidate.request.brand
        )
        return name_matches or class_matches

    @staticmethod
    def _normalized(value: str | None) -> str:
        return "".join((value or "").lower().split())

    @staticmethod
    def _is_delayed(row: AnalysisRow, now: datetime) -> bool:
        if row.expected_arrival_date is None:
            return False
        if row.receipt is not None:
            return row.receipt.received_at.date() > row.expected_arrival_date
        return row.execution is not None and row.expected_arrival_date < now.date()

    @staticmethod
    def _signal(
        code: str,
        risk_type: str,
        matched: bool,
        *,
        facts: dict,
        metrics: dict,
        related: list[int],
        threshold: dict,
        start: str | None,
        end: str | None,
        matched_level: RiskLevel = RiskLevel.MEDIUM,
    ) -> RiskSignal:
        return RiskSignal(
            risk_code=code,
            risk_type=risk_type,
            risk_level=matched_level if matched else RiskLevel.INFO,
            matched=matched,
            facts=facts,
            metrics=metrics,
            related_record_ids=related,
            threshold=threshold,
            time_range={"from": start, "to": end},
        )

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _case_item(
        score: Decimal,
        row: AnalysisRow,
        factors: list[str],
    ) -> SimilarCaseItem:
        return SimilarCaseItem(
            requirement_id=row.request.request_id,
            requirement_no=row.request.request_no,
            status=row.request.status,
            similarity_score=score,
            matched_factors=factors,
            device_profession=row.request.device_profession,
            device_name=row.request.device_name,
            brand=row.request.brand,
            model=row.request.model,
            quantity=row.request.quantity,
            building_id=row.request.building_id,
            building_name=row.building_name,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            actual_total_price=(row.execution.actual_total_price if row.execution else None),
            completed_at=row.request.completed_at,
        )

    def _require_scan_limit(self, rows: list[AnalysisRow]) -> None:
        if len(rows) > self.settings.analytics_max_scan_rows:
            raise AppError(
                "ANALYTICS_SCAN_LIMIT_EXCEEDED",
                "候选记录超过安全扫描上限",
                422,
                details={"max_scan_rows": self.settings.analytics_max_scan_rows},
            )
