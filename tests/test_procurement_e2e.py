import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.notification import NotificationOutbox
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    SupplierBlacklist,
    WarehouseReceipt,
)
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


async def cleanup_requirement(request_id: int) -> None:
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(NotificationOutbox).where(NotificationOutbox.request_id == request_id)
            )
            await session.execute(
                delete(WarehouseReceipt).where(WarehouseReceipt.request_id == request_id)
            )
            await session.execute(
                delete(SupplierBlacklist).where(SupplierBlacklist.source_request_id == request_id)
            )
            await session.execute(
                delete(PurchaseReview).where(PurchaseReview.request_id == request_id)
            )
            await session.execute(
                delete(PurchaseExecution).where(PurchaseExecution.request_id == request_id)
            )
            await session.execute(
                delete(PurchaseOperationLog).where(PurchaseOperationLog.request_id == request_id)
            )
            await session.execute(
                delete(PurchaseRequest).where(PurchaseRequest.request_id == request_id)
            )
    await engine.dispose()


@pytest.fixture(autouse=True)
async def ensure_main_flow_dependencies() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_procurement_flow_with_rejection_and_resubmission() -> None:
    request_id: int | None = None
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        try:
            created = await call(
                client,
                "POST",
                "/api/v1/requirements",
                "test-user-01",
                json={"building_id": 1},
            )
            assert created.status_code == 200, created.text
            request_id = created.json()["data"]["requirement_id"]
            assert created.json()["data"]["status"] == "DRAFT"
            assert created.json()["data"]["version"] == 0

            submit_review_path = f"/api/v1/requirements/{request_id}/submit-review"
            incomplete_submit = await call(
                client,
                "POST",
                submit_review_path,
                "test-user-01",
                json={
                    "expected_version": 0,
                    "assigned_to_employee_id": 90002,
                    "action_token": f"E2E-INCOMPLETE-{uuid4().hex}",
                },
            )
            assert incomplete_submit.status_code == 400
            assert incomplete_submit.json()["code"] == "MISSING_REQUIRED_FIELDS"

            applicant_path = f"/api/v1/requirements/{request_id}/applicant-fields"
            applicant_saved = await call(
                client,
                "PATCH",
                applicant_path,
                "test-user-01",
                json={
                    "expected_version": 0,
                    "fields": {
                        "device_profession": "算力服务器",
                        "device_name": "TEST-E2E交换机",
                        "brand": "TEST-BRAND",
                        "model": "TEST-MODEL",
                        "quantity": "5",
                        "unit": "台",
                        "application_reason": "TEST 端到端流程",
                    },
                },
            )
            assert applicant_saved.status_code == 200, applicant_saved.text
            assert applicant_saved.json()["data"]["fields_complete"] is True
            assert applicant_saved.json()["data"]["version"] == 1

            submitted = await call(
                client,
                "POST",
                submit_review_path,
                "test-user-01",
                json={
                    "expected_version": 1,
                    "assigned_to_employee_id": 90002,
                    "action_token": f"E2E-SUBMIT-{uuid4().hex}",
                },
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["data"]["status"] == "PENDING_REVIEW"

            reject_path = f"/api/v1/requirements/{request_id}/reject"
            rejected = await call(
                client,
                "POST",
                reject_path,
                "test-user-02",
                json={
                    "expected_version": 2,
                    "reason": "请补充型号说明",
                    "action_token": f"E2E-REJECT-{uuid4().hex}",
                },
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["data"]["status"] == "REJECTED"

            applicant_updated = await call(
                client,
                "PATCH",
                applicant_path,
                "test-user-01",
                json={
                    "expected_version": 3,
                    "fields": {"applicant_remark": "已补充型号说明"},
                },
            )
            assert applicant_updated.status_code == 200, applicant_updated.text
            assert applicant_updated.json()["data"]["version"] == 4

            resubmit_path = f"/api/v1/requirements/{request_id}/resubmit-review"
            resubmitted = await call(
                client,
                "POST",
                resubmit_path,
                "test-user-01",
                json={
                    "expected_version": 4,
                    "assigned_to_employee_id": 90002,
                    "action_token": f"E2E-RESUBMIT-{uuid4().hex}",
                },
            )
            assert resubmitted.status_code == 200, resubmitted.text
            assert resubmitted.json()["data"]["version"] == 5

            review_path = f"/api/v1/requirements/{request_id}/review-fields"
            review_saved = await call(
                client,
                "PATCH",
                review_path,
                "test-user-02",
                json={
                    "expected_version": 5,
                    "fields": {
                        "proposed_supplier_id": 92001,
                        "supplier_contact_name": "测试联系人",
                        "supplier_contact_info": "13900009201",
                        "estimated_unit_price": "1000.00",
                        "estimated_total_price": "5000.00",
                        "need_contract": True,
                        "contract_type": "设备采购合同",
                        "payment_method": "验收后付款",
                        "expected_arrival_date": "2026-08-10",
                        "warranty_info": "三年质保",
                    },
                },
            )
            assert review_saved.status_code == 200, review_saved.text
            assert review_saved.json()["data"]["fields_complete"] is True
            assert review_saved.json()["data"]["version"] == 6

            purchaser_path = f"/api/v1/requirements/{request_id}/submit-purchaser"
            sent_to_purchaser = await call(
                client,
                "POST",
                purchaser_path,
                "test-user-02",
                json={
                    "expected_version": 6,
                    "assigned_to_employee_id": 90003,
                    "action_token": f"E2E-PURCHASER-{uuid4().hex}",
                },
            )
            assert sent_to_purchaser.status_code == 200, sent_to_purchaser.text
            assert sent_to_purchaser.json()["data"]["status"] == "PENDING_PURCHASE"

            start_path = f"/api/v1/requirements/{request_id}/start-purchase"
            started = await call(
                client,
                "POST",
                start_path,
                "test-user-03",
                json={
                    "expected_version": 7,
                    "action_token": f"E2E-START-{uuid4().hex}",
                },
            )
            assert started.status_code == 200, started.text
            assert started.json()["data"]["status"] == "PURCHASING"

            purchase_path = f"/api/v1/requirements/{request_id}/purchase-fields"
            invalid_total = await call(
                client,
                "PATCH",
                purchase_path,
                "test-user-03",
                json={
                    "expected_version": 8,
                    "fields": {
                        "supplier_id": 92001,
                        "actual_unit_price": "950.00",
                        "actual_total_price": "999.00",
                        "purchased_at": "2026-08-03T06:30:00Z",
                    },
                },
            )
            assert invalid_total.status_code == 422
            assert invalid_total.json()["code"] == "VALIDATION_ERROR"

            purchase_saved = await call(
                client,
                "PATCH",
                purchase_path,
                "test-user-03",
                json={
                    "expected_version": 8,
                    "fields": {
                        "supplier_id": 92001,
                        "supplier_tax_number": "TEST-CREDIT-92001",
                        "bank_name": "测试银行",
                        "bank_account": "TEST-ACCOUNT-92001",
                        "registered_address": "测试市采购路1号",
                        "contract_contact_info": "测试联系人 13900009201",
                        "actual_unit_price": "950.00",
                        "actual_total_price": "4750.00",
                        "tax_rate": "13.00",
                        "purchased_at": "2026-08-03T06:30:00Z",
                        "purchase_remark": "TEST 正常采购",
                        "update_supplier_profile": False,
                    },
                },
            )
            assert purchase_saved.status_code == 200, purchase_saved.text
            assert purchase_saved.json()["data"]["version"] == 9

            warehouse_path = f"/api/v1/requirements/{request_id}/submit-warehouse"
            sent_to_warehouse = await call(
                client,
                "POST",
                warehouse_path,
                "test-user-03",
                json={
                    "expected_version": 9,
                    "assigned_to_employee_id": 90004,
                    "action_token": f"E2E-WAREHOUSE-{uuid4().hex}",
                },
            )
            assert sent_to_warehouse.status_code == 200, sent_to_warehouse.text
            assert sent_to_warehouse.json()["data"]["status"] == "PENDING_WAREHOUSE"

            receipt_path = f"/api/v1/requirements/{request_id}/warehouse-fields"
            missing_short_receipt_remark = await call(
                client,
                "PATCH",
                receipt_path,
                "test-user-04",
                json={
                    "expected_version": 10,
                    "fields": {
                        "warehouse_location": "TEST-E2E-A区",
                        "received_quantity": "4",
                    },
                },
            )
            assert missing_short_receipt_remark.status_code == 422
            assert missing_short_receipt_remark.json()["code"] == "VALIDATION_ERROR"

            receipt_saved = await call(
                client,
                "PATCH",
                receipt_path,
                "test-user-04",
                json={
                    "expected_version": 10,
                    "fields": {
                        "warehouse_location": "TEST-E2E-A区",
                        "received_quantity": "4",
                        "receipt_remark": "申请5台，1台延期到货",
                    },
                },
            )
            assert receipt_saved.status_code == 200, receipt_saved.text
            assert receipt_saved.json()["data"]["version"] == 11

            complete_path = f"/api/v1/requirements/{request_id}/complete"
            completed = await call(
                client,
                "POST",
                complete_path,
                "test-user-04",
                json={
                    "expected_version": 11,
                    "action_token": f"E2E-COMPLETE-{uuid4().hex}",
                },
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["data"]["status"] == "COMPLETED"
            assert completed.json()["data"]["version"] == 12
            assert completed.json()["data"]["current_handler"] is None

            detail_path = f"/api/v1/requirements/{request_id}"
            detail = await call(
                client,
                "GET",
                detail_path,
                "test-user-01",
            )
            assert detail.status_code == 200, detail.text
            detail_data = detail.json()["data"]
            assert detail_data["status"] == "COMPLETED"
            assert len(detail_data["review_records"]) == 2
            assert detail_data["warehouse_receipt"]["received_quantity"] == "4.000"
            assert detail_data["purchase_execution"]["bank_account"] == "TEST****2001"
            assert (
                detail_data["purchase_execution"]["purchased_at"]
                == "2026-08-03T14:30:00"
            )

            listed = await call(
                client,
                "GET",
                "/api/v1/requirements",
                "test-user-01",
                params={"view": "CREATED_BY_ME", "page": 1, "page_size": 100},
            )
            assert listed.status_code == 200, listed.text
            assert request_id in {item["requirement_id"] for item in listed.json()["data"]["items"]}

            await engine.dispose()
            async with async_session_factory() as session:
                log_count = await session.scalar(
                    select(func.count())
                    .select_from(PurchaseOperationLog)
                    .where(PurchaseOperationLog.request_id == request_id)
                )
                notification_count = await session.scalar(
                    select(func.count())
                    .select_from(NotificationOutbox)
                    .where(NotificationOutbox.request_id == request_id)
                )
            assert log_count == 8
            assert notification_count == 3
        finally:
            if request_id is not None:
                await cleanup_requirement(request_id)


@pytest.mark.asyncio
async def test_building_manager_can_list_scope_and_edit_pending_application() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        building_scope = await call(
            client,
            "GET",
            "/api/v1/requirements",
            "test-user-02",
            params={"view": "BUILDING_SCOPE", "page": 1, "page_size": 100},
        )
        assert building_scope.status_code == 200, building_scope.text
        building_items = building_scope.json()["data"]["items"]
        assert building_items
        assert 91002 in {item["requirement_id"] for item in building_items}

        detail_path = "/api/v1/requirements/91002"
        detail = await call(client, "GET", detail_path, "test-user-02")
        assert detail.status_code == 200, detail.text
        version = detail.json()["data"]["version"]
        assert "SAVE_APPLICANT_FIELDS" in detail.json()["data"]["allowed_actions"]

        applicant_path = "/api/v1/requirements/91002/applicant-fields"
        edited = await call(
            client,
            "PATCH",
            applicant_path,
            "test-user-02",
            json={
                "expected_version": version,
                "fields": {
                    "brand": "TEST-楼长修订品牌",
                    "applicant_remark": "TEST 楼长补充需求说明",
                },
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["version"] == version + 1

        edited_detail = await call(client, "GET", detail_path, "test-user-02")
        assert edited_detail.json()["data"]["applicant_fields"]["brand"] == "TEST-楼长修订品牌"

        cross_building = await call(
            client,
            "GET",
            "/api/v1/requirements",
            "test-user-07",
            params={"view": "BUILDING_SCOPE", "page": 1, "page_size": 100},
        )
        assert cross_building.status_code == 200, cross_building.text
        assert all(
            item["requirement_id"] not in {91001, 91002, 91003, 91004, 91005, 91006, 91007}
            for item in cross_building.json()["data"]["items"]
        )
