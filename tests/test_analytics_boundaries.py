import asyncio
from datetime import datetime
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.domain.identity import CurrentUser
from app.models.procurement import PurchaseRequest
from app.repositories.analytics import AnalysisRow
from app.schemas.analytics import PurchaseQueryRequest
from app.services.analytics import AnalyticsService
from app.services.risk_analysis import RiskAnalysisService


def current_user() -> CurrentUser:
    return CurrentUser(
        employee_id=1,
        employee_no="E001",
        name="测试用户",
        mobile=None,
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
        roles=(),
        buildings=(),
    )


class SlowRepository:
    async def query_rows(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        return []


class OversizedRepository:
    async def query_rows(self, *args, **kwargs):
        return [object(), object(), object()]


@pytest.mark.asyncio
async def test_analytics_timeout_is_classified() -> None:
    settings = get_settings().model_copy(update={"analytics_query_timeout_seconds": 0.001})
    service = AnalyticsService(repository=SlowRepository(), settings=settings)

    with pytest.raises(AppError) as captured:
        await service.purchase_query(None, current_user(), PurchaseQueryRequest())

    assert captured.value.code == "ANALYTICS_QUERY_TIMEOUT"
    assert captured.value.status_code == 504


@pytest.mark.asyncio
async def test_analytics_scan_limit_requires_narrower_query() -> None:
    settings = get_settings().model_copy(update={"analytics_max_scan_rows": 2})
    service = AnalyticsService(repository=OversizedRepository(), settings=settings)

    with pytest.raises(AppError) as captured:
        await service.purchase_query(None, current_user(), PurchaseQueryRequest())

    assert captured.value.code == "ANALYTICS_SCAN_LIMIT_EXCEEDED"
    assert captured.value.details == {"max_scan_rows": 2}


def test_all_risk_rules_have_stable_non_matching_case() -> None:
    request = PurchaseRequest(
        request_id=1,
        request_no="UNIT-ISOLATED",
        building_id=1,
        applicant_employee_id=1,
        applicant_platform_type_snapshot="TEST_PLATFORM",
        applicant_platform_user_id_snapshot="user-1",
        applicant_name_snapshot="测试用户",
        device_profession="运维工具",
        device_name="完全独立设备",
        brand="UNIQUE",
        model="UNIQUE-1",
        quantity=Decimal("1"),
        status="DRAFT",
        created_at=datetime(2026, 8, 5, 9, 0, 0),
    )
    row = AnalysisRow(
        request=request,
        building_name="一号楼",
        execution=None,
        receipt=None,
        expected_arrival_date=None,
        proposed_supplier_id=None,
        proposed_supplier_name=None,
        estimated_unit_price=None,
    )

    signals = RiskAnalysisService()._evaluate(
        row,
        [],
        set(),
        datetime(2026, 8, 5, 10, 0, 0),
    )

    assert len(signals) == 7
    assert all(signal.matched is False for signal in signals)
