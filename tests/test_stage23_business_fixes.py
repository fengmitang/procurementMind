import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.gateway_auth import build_gateway_signature
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.identity import (
    AdminOperationLog,
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
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


@pytest.fixture(autouse=True)
async def reset_demo_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_supplier_default_list_and_building_scoped_risks() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        default_list = await call(client, "GET", "/api/v1/suppliers", "test-user-02")
        assert default_list.status_code == 200, default_list.text
        assert default_list.json()["data"]["total"] >= 5
        assert all("status" in item for item in default_list.json()["data"]["items"])

        risks = await call(
            client,
            "GET",
            "/api/v1/suppliers/risks/building-scope",
            "test-user-02",
        )
        assert risks.status_code == 200, risks.text
        items = risks.json()["data"]["items"]
        assert items
        assert {item["source_requirement_id"] for item in items}.issubset({91003, 91004})
        assert all("is_effective" in item for item in items)

        denied = await call(
            client,
            "GET",
            "/api/v1/suppliers/risks/building-scope",
            "test-user-01",
        )
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_warehouse_quantity_boundaries() -> None:
    path = "/api/v1/requirements/91006/warehouse-fields"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        less = await call(
            client,
            "PATCH",
            path,
            "test-user-04",
            json={
                "expected_version": 5,
                "fields": {"warehouse_location": "A-01", "received_quantity": "5"},
            },
        )
        assert less.status_code == 422
        assert less.json()["data"]["reason"] == "PARTIAL_RECEIPT"

        equal = await call(
            client,
            "PATCH",
            path,
            "test-user-04",
            json={
                "expected_version": 5,
                "fields": {"warehouse_location": "A-01", "received_quantity": "6"},
            },
        )
        assert equal.status_code == 200, equal.text

        greater = await call(
            client,
            "PATCH",
            path,
            "test-user-04",
            json={
                "expected_version": 6,
                "fields": {"warehouse_location": "A-01", "received_quantity": "7"},
            },
        )
        assert greater.status_code == 200, greater.text


@pytest.mark.asyncio
async def test_admin_employee_crud_and_read_only_scope_permissions() -> None:
    employee_id: int | None = None
    platform_user_id = f"stage23-{uuid4().hex}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await call(client, "GET", "/api/v1/admin/employees", "test-user-01")
        assert denied.status_code == 403

        references = await call(client, "GET", "/api/v1/admin/references", "test-user-05")
        assert references.status_code == 200, references.text
        assert references.json()["data"]["roles"]
        assert references.json()["data"]["buildings"]

        payload = {
            "employee_no": f"STAGE23-{uuid4().hex[:8]}",
            "name": "阶段二十三测试员工",
            "mobile": "13800009999",
            "status": True,
            "role_codes": ["APPLICANT"],
            "building_ids": [1],
            "primary_building_id": 1,
            "platform_type": "TEST_PLATFORM",
            "platform_user_id": platform_user_id,
            "action_token": f"ADMIN-CREATE-{uuid4().hex}",
        }
        created = await call(
            client,
            "POST",
            "/api/v1/admin/employees",
            "test-user-05",
            json=payload,
        )
        assert created.status_code == 200, created.text
        employee_id = created.json()["data"]["employee_id"]

        payload.update(
            name="阶段二十三已修改员工",
            role_codes=["APPLICANT", "PURCHASER"],
            action_token=f"ADMIN-UPDATE-{uuid4().hex}",
        )
        updated = await call(
            client,
            "PATCH",
            f"/api/v1/admin/employees/{employee_id}",
            "test-user-05",
            json=payload,
        )
        assert updated.status_code == 200, updated.text
        assert {role["role_code"] for role in updated.json()["data"]["roles"]} == {
            "APPLICANT",
            "PURCHASER",
        }

        deactivated = await call(
            client,
            "DELETE",
            f"/api/v1/admin/employees/{employee_id}",
            "test-user-05",
            json={"action_token": f"ADMIN-DEACTIVATE-{uuid4().hex}"},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["data"]["status"] is False

        admin_scope = await call(
            client,
            "GET",
            "/api/v1/requirements",
            "test-user-05",
            params={"view": "ADMIN_SCOPE"},
        )
        assert admin_scope.status_code == 200, admin_scope.text
        denied_scope = await call(
            client,
            "GET",
            "/api/v1/requirements",
            "test-user-01",
            params={"view": "ADMIN_SCOPE"},
        )
        assert denied_scope.status_code == 403

    if employee_id is not None:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(AdminOperationLog).where(
                        AdminOperationLog.target_employee_id == employee_id
                    )
                )
                await session.execute(
                    delete(EmployeeExternalIdentity).where(
                        EmployeeExternalIdentity.employee_id == employee_id
                    )
                )
                await session.execute(
                    delete(EmployeeRole).where(EmployeeRole.employee_id == employee_id)
                )
                await session.execute(
                    delete(EmployeeBuilding).where(EmployeeBuilding.employee_id == employee_id)
                )
                await session.execute(delete(Employee).where(Employee.employee_id == employee_id))
