import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.procurement import PurchaseExecution, PurchaseRequest, Supplier
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
async def test_supplier_search_detail_masking_creation_and_conflict() -> None:
    created_supplier_id: int | None = None
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        search_path = "/api/v1/suppliers"
        search = await call(
            client,
            "GET",
            search_path,
            "test-user-01",
            params={"keyword": "TEST-常规"},
        )
        assert search.status_code == 200, search.text
        assert search.json()["data"]["items"][0]["supplier_id"] == 92001
        assert search.json()["data"]["items"][0]["blacklist_status"] == "NORMAL"

        detail_path = "/api/v1/suppliers/92001"
        applicant_detail = await call(
            client,
            "GET",
            detail_path,
            "test-user-01",
        )
        purchaser_detail = await call(
            client,
            "GET",
            detail_path,
            "test-user-03",
        )
        assert applicant_detail.status_code == 200, applicant_detail.text
        assert applicant_detail.json()["data"]["bank_account"] == "TEST****2001"
        assert purchaser_detail.json()["data"]["bank_account"] == "TEST-ACCOUNT-92001"

        create_path = "/api/v1/suppliers"
        payload = {
            "supplier_name": f"接口测试供应商-{uuid4().hex}",
            "unified_social_credit_code": f"TEST-NEW-{uuid4().hex}",
            "bank_name": "接口测试银行",
            "bank_account": "6222000012345678",
        }
        denied = await call(
            client,
            "POST",
            create_path,
            "test-user-01",
            json=payload,
        )
        assert denied.status_code == 403

        created = await call(
            client,
            "POST",
            create_path,
            "test-user-03",
            json=payload,
        )
        assert created.status_code == 200, created.text
        created_supplier_id = created.json()["data"]["supplier_id"]

        conflict = await call(
            client,
            "POST",
            create_path,
            "test-user-03",
            json=payload,
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "SUPPLIER_MATCH_CONFLICT"

    if created_supplier_id is not None:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(Supplier).where(Supplier.supplier_id == created_supplier_id)
                )


@pytest.mark.asyncio
async def test_blacklist_lifecycle_and_permissions() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_path = "/api/v1/suppliers/92002/blacklist"
        created = await call(
            client,
            "POST",
            create_path,
            "test-user-02",
            json={
                "requirement_id": 91007,
                "blacklist_type": "履约问题",
                "reason": "接口测试：到货质量不符合要求",
                "duration_type": "LIMITED",
                "start_at": "2026-07-30T10:00:00+08:00",
                "end_at": "2026-12-31T23:59:59+08:00",
                "action_token": f"BLACKLIST-{uuid4().hex}",
            },
        )
        assert created.status_code == 200, created.text
        blacklist_id = created.json()["data"]["blacklist_id"]

        detail_path = "/api/v1/suppliers/92002"
        detail = await call(client, "GET", detail_path, "test-user-02")
        assert detail.json()["data"]["blacklist"]["status"] == "BLACKLISTED"

        release_path = f"/api/v1/suppliers/92002/blacklists/{blacklist_id}/release"
        denied = await call(
            client,
            "POST",
            release_path,
            "test-user-07",
            json={
                "reason": "无权解除测试",
                "action_token": f"RELEASE-DENIED-{uuid4().hex}",
            },
        )
        assert denied.status_code == 403

        released = await call(
            client,
            "POST",
            release_path,
            "test-user-02",
            json={
                "reason": "供应商整改完成",
                "action_token": f"RELEASE-{uuid4().hex}",
            },
        )
        assert released.status_code == 200, released.text
        assert released.json()["data"]["status"] == "RELEASED"

        detail = await call(client, "GET", detail_path, "test-user-02")
        assert detail.json()["data"]["blacklist"] == {
            "status": "HISTORY",
            "history_count": 1,
        }


@pytest.mark.asyncio
async def test_recommendations_use_real_history_and_filter_active_blacklist() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(PurchaseRequest)
                .where(PurchaseRequest.request_id.in_([91002, 91007]))
                .values(device_profession="传输", device_name="交换机")
            )
            await session.execute(
                update(PurchaseRequest)
                .where(PurchaseRequest.request_id == 91007)
                .values(
                    request_no="REC-HISTORY-91007",
                    brand="华为",
                    model="S5735",
                )
            )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        product_path = "/api/v1/recommendations/products"
        products = await call(
            client,
            "GET",
            product_path,
            "test-user-01",
            params={
                "device_profession": "传输",
                "device_name": "交换机",
            },
        )
        assert products.status_code == 200, products.text
        assert products.json()["data"]["items"] == [
            {
                "brand": "华为",
                "model": "S5735",
                "historical_count": 1,
                "last_purchased_at": "2026-07-06T14:00:00",
            }
        ]

        history_path = "/api/v1/recommendations/purchase-history"
        history = await call(
            client,
            "GET",
            history_path,
            "test-user-02",
            params={"requirement_id": 91002},
        )
        assert history.status_code == 200, history.text
        assert [item["requirement_id"] for item in history.json()["data"]["items"]] == [91007]

        suppliers_path = "/api/v1/recommendations/suppliers"
        suppliers = await call(
            client,
            "GET",
            suppliers_path,
            "test-user-02",
            params={"requirement_id": 91002},
        )
        assert suppliers.status_code == 200, suppliers.text
        assert [item["supplier_id"] for item in suppliers.json()["data"]["items"]] == [92002]

        blacklist_path = "/api/v1/suppliers/92002/blacklist"
        blacklisted = await call(
            client,
            "POST",
            blacklist_path,
            "test-user-02",
            json={
                "requirement_id": 91007,
                "blacklist_type": "履约问题",
                "reason": "接口测试：推荐时排除有效黑名单",
                "duration_type": "PERMANENT",
                "start_at": "2026-07-30T10:00:00+08:00",
                "action_token": f"REC-BLACKLIST-{uuid4().hex}",
            },
        )
        assert blacklisted.status_code == 200, blacklisted.text

        history_after_blacklist = await call(
            client,
            "GET",
            history_path,
            "test-user-02",
            params={"requirement_id": 91002},
        )
        assert (
            history_after_blacklist.json()["data"]["items"][0]["blacklist_status"] == "BLACKLISTED"
        )

        suppliers_after_blacklist = await call(
            client,
            "GET",
            suppliers_path,
            "test-user-02",
            params={"requirement_id": 91002},
        )
        assert suppliers_after_blacklist.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_purchase_snapshot_only_updates_master_when_explicitly_confirmed() -> None:
    purchase_path = "/api/v1/requirements/91005/purchase-fields"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        snapshot_only = await call(
            client,
            "PATCH",
            purchase_path,
            "test-user-03",
            json={
                "expected_version": 4,
                "fields": {
                    "supplier_id": 92001,
                    "supplier_tax_number": "SNAPSHOT-CREDIT",
                    "bank_name": "本次采购银行",
                    "bank_account": "SNAPSHOT-ACCOUNT",
                    "registered_address": "本次采购地址",
                    "contract_contact_info": "本次采购联系人",
                    "actual_unit_price": "100.00",
                    "actual_total_price": "500.00",
                    "purchased_at": "2026-07-30T10:00:00+08:00",
                    "update_supplier_profile": False,
                },
            },
        )
        assert snapshot_only.status_code == 200, snapshot_only.text

        async with async_session_factory() as session:
            supplier = await session.get(Supplier, 92001)
            execution = await session.scalar(
                select(PurchaseExecution).where(PurchaseExecution.request_id == 91005)
            )
            assert supplier is not None
            assert execution is not None
            assert supplier.bank_account == "TEST-ACCOUNT-92001"
            assert execution.supplier_bank_account_snapshot == "SNAPSHOT-ACCOUNT"

        sync_master = await call(
            client,
            "PATCH",
            purchase_path,
            "test-user-03",
            json={
                "expected_version": 5,
                "fields": {
                    "supplier_id": 92001,
                    "supplier_tax_number": "TEST-CREDIT-92001",
                    "bank_name": "同步后的银行",
                    "bank_account": "SYNCED-ACCOUNT",
                    "registered_address": "同步后的地址",
                    "contract_contact_info": "同步后的联系人",
                    "actual_unit_price": "100.00",
                    "actual_total_price": "500.00",
                    "purchased_at": "2026-07-30T11:00:00+08:00",
                    "update_supplier_profile": True,
                },
            },
        )
        assert sync_master.status_code == 200, sync_master.text

        async with async_session_factory() as session:
            supplier = await session.get(Supplier, 92001)
            execution = await session.scalar(
                select(PurchaseExecution).where(PurchaseExecution.request_id == 91005)
            )
            assert supplier is not None
            assert execution is not None
            assert supplier.bank_account == "SYNCED-ACCOUNT"
            assert execution.supplier_bank_account_snapshot == "SYNCED-ACCOUNT"
