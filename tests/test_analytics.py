import time
from datetime import date, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import engine
from app.main import app
from scripts.seed_demo_data import seed_demo_data


def signed_headers(method: str, path: str, platform_user_id: str) -> dict[str, str]:
    settings = get_settings()
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    platform_type = "TEST_PLATFORM"
    return {
        "X-Platform-Type": platform_type,
        "X-Platform-User-Id": platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": nonce,
        "X-Gateway-Signature": build_gateway_signature(
            secret=settings.identity_gateway_secret,
            method=method,
            path=path,
            platform_type=platform_type,
            platform_user_id=platform_user_id,
            timestamp=timestamp,
            nonce=nonce,
        ),
    }


async def call(
    client: AsyncClient,
    method: str,
    path: str,
    platform_user_id: str,
    **kwargs,
):
    return await client.request(
        method,
        path,
        headers=signed_headers(method, path, platform_user_id),
        **kwargs,
    )


@pytest.fixture(autouse=True)
async def reset_demo_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_controlled_purchase_query_matches_seeded_standard_answers() -> None:
    path = "/api/v1/analytics/purchase-query"
    payload = {
        "created_from": "2026-08-01",
        "created_to": "2026-08-05",
        "device_professions": ["算力服务器"],
        "group_by": "BRAND",
        "aggregations": [
            "COUNT",
            "AVERAGE_UNIT_PRICE",
            "MEDIAN_UNIT_PRICE",
            "TOTAL_AMOUNT",
        ],
        "page_size": 100,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await call(client, "POST", path, "test-user-05", json=payload)
        other_building = await call(client, "POST", path, "test-user-07", json=payload)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 9
    assert data["summary"] == {
        "count": 9,
        "average_unit_price": "1112.50",
        "median_unit_price": "950.00",
        "total_amount": "34350.00",
    }
    assert data["groups"] == [
        {
            "key": "TEST-BRAND",
            "label": "TEST-BRAND",
            "metrics": data["summary"],
        }
    ]
    assert data["effective_query"]["max_scan_rows"] == 5000
    assert other_building.status_code == 200
    assert other_building.json()["data"]["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("group_by", ["STATUS", "MONTH"])
async def test_purchase_query_supports_status_and_month_groups(group_by: str) -> None:
    path = "/api/v1/analytics/purchase-query"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await call(
            client,
            "POST",
            path,
            "test-user-05",
            json={
                "created_from": "2026-01-01",
                "created_to": "2026-12-31",
                "group_by": group_by,
                "aggregations": ["COUNT", "TOTAL_AMOUNT"],
                "page_size": 100,
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["effective_query"]["group_by"] == group_by
    assert sum(group["metrics"]["count"] for group in data["groups"]) == data["summary"]["count"]
    if group_by == "MONTH":
        assert all(len(group["key"]) == 7 and group["key"][4] == "-" for group in data["groups"])


@pytest.mark.asyncio
async def test_purchase_query_can_scope_to_current_applicant_and_returns_card_fields() -> None:
    path = "/api/v1/analytics/purchase-query"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await call(
            client,
            "POST",
            path,
            "test-user-01",
            json={
                "created_from": "2026-01-01",
                "created_to": "2026-12-31",
                "created_by_me": True,
                "page_size": 100,
            },
        )

    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert items
    assert all(item["requirement_no"] for item in items)
    assert all("current_handler_name" in item and "unit" in item for item in items)


@pytest.mark.asyncio
async def test_query_dsl_rejects_unknown_sql_and_invalid_ranges() -> None:
    path = "/api/v1/analytics/purchase-query"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        arbitrary_sql = await call(
            client,
            "POST",
            path,
            "test-user-05",
            json={"sql": "SELECT * FROM employee"},
        )
        invalid_range = await call(
            client,
            "POST",
            path,
            "test-user-05",
            json={"created_from": "2024-01-01", "created_to": "2026-08-05"},
        )
        invalid_building = await call(
            client,
            "POST",
            path,
            "test-user-02",
            json={"building_ids": [2]},
        )
        invalid_status = await call(
            client,
            "POST",
            path,
            "test-user-05",
            json={"statuses": ["DROP_TABLE"]},
        )

    assert arbitrary_sql.status_code == 422
    assert invalid_range.status_code == 422
    assert invalid_building.status_code == 403
    assert invalid_building.json()["code"] == "BUILDING_NOT_ALLOWED"
    assert invalid_status.status_code == 422


@pytest.mark.asyncio
async def test_excluding_delayed_suppliers_uses_visible_query_range() -> None:
    path = "/api/v1/analytics/purchase-query"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await call(
            client,
            "POST",
            path,
            "test-user-05",
            json={
                "created_from": "2026-08-01",
                "created_to": "2026-08-05",
                "exclude_delayed_suppliers": True,
                "page_size": 100,
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 5
    assert all(item["supplier_id"] != 92001 for item in data["items"])
    assert data["warnings"] == ["延期供应商按本次查询时间范围内的可见记录判定"]


@pytest.mark.asyncio
async def test_risk_signals_are_factual_and_permission_scoped() -> None:
    path = "/api/v1/requirements/91006/risk-signals"
    denied_path = "/api/v1/requirements/91007/risk-signals"
    quantity_path = "/api/v1/requirements/91008/risk-signals"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await call(client, "GET", path, "test-user-01")
        quantity_response = await call(client, "GET", quantity_path, "test-user-01")
        denied = await call(client, "GET", denied_path, "test-user-07")

    assert response.status_code == 200, response.text
    signals = {item["risk_code"]: item for item in response.json()["data"]["signals"]}
    assert len(signals) == 7
    assert signals["DELIVERY_DELAY"]["matched"] is True
    assert signals["LONG_PENDING_RECEIPT"]["matched"] is True
    assert signals["DUPLICATE_APPLICATION"]["matched"] is True
    assert signals["SIMILAR_APPLICATION"]["matched"] is True
    expected_pending_days = (datetime.now().date() - date(2026, 7, 6)).days
    assert signals["LONG_PENDING_RECEIPT"]["facts"]["pending_days"] == expected_pending_days
    quantity_signals = {
        item["risk_code"]: item for item in quantity_response.json()["data"]["signals"]
    }
    assert quantity_signals["QUANTITY_DEVIATION"]["matched"] is True
    assert quantity_signals["QUANTITY_DEVIATION"]["facts"]["receipt_variance"] == "-2.000"
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_seeded_data_covers_price_blacklist_and_non_matching_risks() -> None:
    price_path = "/api/v1/requirements/91009/risk-signals"
    blacklist_path = "/api/v1/requirements/91005/risk-signals"
    normal_path = "/api/v1/requirements/91007/risk-signals"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        price = await call(client, "GET", price_path, "test-user-01")
        blacklist = await call(client, "GET", blacklist_path, "test-user-01")
        normal = await call(client, "GET", normal_path, "test-user-01")

    price_signals = {item["risk_code"]: item for item in price.json()["data"]["signals"]}
    blacklist_signals = {item["risk_code"]: item for item in blacklist.json()["data"]["signals"]}
    normal_signals = {item["risk_code"]: item for item in normal.json()["data"]["signals"]}
    assert price_signals["PRICE_DEVIATION"]["matched"] is True
    assert price_signals["QUANTITY_DEVIATION"]["matched"] is True
    assert price_signals["QUANTITY_DEVIATION"]["facts"]["receipt_variance"] == "1.000"
    assert blacklist_signals["SUPPLIER_BLACKLIST"]["matched"] is True
    assert blacklist_signals["SUPPLIER_BLACKLIST"]["risk_level"] == "HIGH"
    assert normal_signals["PRICE_DEVIATION"]["matched"] is False
    assert normal_signals["QUANTITY_DEVIATION"]["matched"] is False
    assert normal_signals["DELIVERY_DELAY"]["matched"] is False
    assert normal_signals["LONG_PENDING_RECEIPT"]["matched"] is False


@pytest.mark.asyncio
async def test_supplier_performance_returns_ratio_numerators_and_denominators() -> None:
    path = "/api/v1/suppliers/92001/performance"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await call(
            client,
            "GET",
            path,
            "test-user-01",
            params={"created_from": "2026-08-01", "created_to": "2026-08-05"},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["historical_purchase_count"] == 3
    assert data["delay"] == {"numerator": 1, "denominator": 3, "ratio": "0.3333"}
    assert data["quantity_anomaly"] == {
        "numerator": 2,
        "denominator": 2,
        "ratio": "1.0000",
    }
    assert data["average_delivery_days"] == "3.50"
    assert data["current_blacklist_status"] == "NORMAL"


@pytest.mark.asyncio
async def test_similar_cases_are_explainable_and_exclude_current_request() -> None:
    path = "/api/v1/requirements/91007/similar-cases"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await call(client, "GET", path, "test-user-01", params={"limit": 5})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["algorithm"] == "RULE_WEIGHTED_V1"
    assert data["items"]
    assert all(item["requirement_id"] != 91007 for item in data["items"])
    assert all(item["matched_factors"] for item in data["items"])
    assert all("similarity_score" in item for item in data["items"])
