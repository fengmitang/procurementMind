import time
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


async def get(
    client: AsyncClient,
    path: str,
    platform_user_id: str,
    **kwargs,
):
    return await client.get(
        path,
        headers=signed_headers("GET", path, platform_user_id),
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
async def test_purchase_records_filter_and_role_scope() -> None:
    path = "/api/v1/purchase-records"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        applicant = await get(
            client,
            path,
            "test-user-01",
            params={"supplier_id": 92002},
        )
        assert applicant.status_code == 200, applicant.text
        assert applicant.json()["data"]["total"] == 1
        item = applicant.json()["data"]["items"][0]
        assert item["requirement_id"] == 91007
        assert item["supplier_id"] == 92002
        assert item["supplier_name"] == "TEST-供应商B（本次采购快照旧名称）"
        assert item["submitted_at"] == "2026-07-01T09:00:00"
        assert item["reviewed_at"] == "2026-07-03T10:00:00"
        assert item["purchased_at"] == "2026-07-06T14:00:00"
        assert item["received_at"] == "2026-07-08T16:00:00"
        assert item["completed_at"] == "2026-07-08T16:00:00"

        other_building_manager = await get(
            client,
            path,
            "test-user-07",
        )
        assert other_building_manager.status_code == 200
        assert other_building_manager.json()["data"]["items"] == []

        invalid_dates = await get(
            client,
            path,
            "test-user-05",
            params={
                "created_from": "2026-08-01",
                "created_to": "2026-07-01",
            },
        )
        assert invalid_dates.status_code == 422
        assert invalid_dates.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_timeline_masks_contacts_and_authorized_roles_can_reveal_them() -> None:
    path = "/api/v1/requirements/91007/timeline"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        timeline = await get(client, path, "test-user-01")
        assert timeline.status_code == 200, timeline.text
        items = timeline.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["log_id"] == 99007
        assert items[0]["action_type"] == "WAREHOUSE_RECEIVE"
        assert items[0]["to_status"] == "COMPLETED"
        assert items[0]["operator_name"] == "测试仓库管理员"
        assert items[0]["operator_role_name"] == "仓库管理员"
        assert items[0]["operator_mobile_masked"] == "138****9004"
        assert "action_token" not in items[0]
        assert "operator_mobile_snapshot" not in items[0]

        contact_path = "/api/v1/requirements/91007/timeline/99007/contact"
        contact = await get(client, contact_path, "test-user-01")
        assert contact.status_code == 200, contact.text
        assert contact.json()["data"] == {
            "employee_name": "测试仓库管理员",
            "mobile": "13800009004",
        }

        for platform_user_id in ("test-user-02", "test-user-04", "test-user-05"):
            authorized_contact = await get(client, contact_path, platform_user_id)
            assert authorized_contact.status_code == 200, authorized_contact.text
            assert authorized_contact.json()["data"]["mobile"] == "13800009004"

        purchaser_contact_path = (
            "/api/v1/requirements/91006/timeline/99006/contact"
        )
        purchaser_contact = await get(
            client,
            purchaser_contact_path,
            "test-user-03",
        )
        assert purchaser_contact.status_code == 200, purchaser_contact.text
        assert purchaser_contact.json()["data"]["mobile"] == "13800009003"

        denied = await get(client, path, "test-user-07")
        assert denied.status_code == 403
        denied_contact = await get(client, contact_path, "test-user-07")
        assert denied_contact.status_code == 403
