import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.gateway_auth import build_gateway_signature
from app.db.session import engine
from app.domain.identity import CurrentUser, UserBuilding, UserRole
from app.main import app
from app.services.permissions import require_any_role, require_building_membership
from scripts.seed_demo_data import seed_demo_data


@pytest.fixture(scope="module", autouse=True)
async def ensure_demo_identities() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def release_database_pool_after_test() -> None:
    yield
    await engine.dispose()


def signed_headers(
    platform_user_id: str,
    *,
    path: str = "/api/v1/users/me",
    nonce: str | None = None,
    signature_override: str | None = None,
) -> dict[str, str]:
    settings = get_settings()
    platform_type = "TEST_PLATFORM"
    timestamp = str(int(time.time()))
    gateway_nonce = nonce or uuid4().hex
    signature = build_gateway_signature(
        secret=settings.identity_gateway_secret,
        method="GET",
        path=path,
        platform_type=platform_type,
        platform_user_id=platform_user_id,
        timestamp=timestamp,
        nonce=gateway_nonce,
    )
    return {
        "X-Platform-Type": platform_type,
        "X-Platform-User-Id": platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": gateway_nonce,
        "X-Gateway-Signature": signature_override or signature,
    }


@pytest.mark.asyncio
async def test_get_current_user_from_signed_gateway_identity() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/users/me",
            headers=signed_headers("test-user-01"),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["employee_id"] == 90001
    assert data["name"] == "测试需求人"
    assert data["mobile"] == "138****9001"
    assert [role["role_code"] for role in data["roles"]] == ["APPLICANT"]
    assert [building["building_id"] for building in data["buildings"]] == [1]


@pytest.mark.asyncio
async def test_rejects_forged_gateway_signature() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/users/me",
            headers=signed_headers("test-user-01", signature_override="0" * 64),
        )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_IDENTITY_SIGNATURE"


@pytest.mark.asyncio
async def test_rejects_replayed_gateway_identity() -> None:
    headers = signed_headers("test-user-01")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.get("/api/v1/users/me", headers=headers)
        second = await client.get("/api/v1/users/me", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["code"] == "IDENTITY_REPLAYED"


@pytest.mark.asyncio
async def test_rejects_unknown_and_disabled_users() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        unknown = await client.get(
            "/api/v1/users/me",
            headers=signed_headers("test-user-unknown"),
        )
        disabled = await client.get(
            "/api/v1/users/me",
            headers=signed_headers("test-user-06"),
        )

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "USER_NOT_FOUND"
    assert disabled.status_code == 403
    assert disabled.json()["code"] == "USER_DISABLED"


@pytest.mark.asyncio
async def test_handler_candidates_follow_role_and_building_scope() -> None:
    path = "/api/v1/requirements/91001/handler-candidates"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            path,
            params={"target_role": "BUILDING_MANAGER"},
            headers=signed_headers("test-user-01", path=path),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["employee_id"] for item in data["items"]] == [90002]
    assert data["auto_selected_employee_id"] == 90002


@pytest.mark.asyncio
async def test_cross_building_manager_cannot_query_handler_candidates() -> None:
    path = "/api/v1/requirements/91001/handler-candidates"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            path,
            params={"target_role": "PURCHASER"},
            headers=signed_headers("test-user-07", path=path),
        )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_role_and_building_permissions() -> None:
    user = CurrentUser(
        employee_id=90002,
        employee_no="TEST-E002",
        name="测试一号楼楼长",
        mobile="13800009002",
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-02",
        roles=(UserRole(2, "BUILDING_MANAGER", "楼长"),),
        buildings=(UserBuilding(1, "一号楼", True),),
    )

    require_any_role(user, "BUILDING_MANAGER")
    require_building_membership(user, 1)

    with pytest.raises(AppError, match="角色权限"):
        require_any_role(user, "PURCHASER")
    with pytest.raises(AppError, match="无权访问"):
        require_building_membership(user, 2)
