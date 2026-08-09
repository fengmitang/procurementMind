from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import demo as demo_route
from app.db.session import engine
from app.main import app
from app.schemas.demo import DemoAgentActionRequest, DemoAgentChatRequest
from scripts.seed_demo_data import seed_demo_data


@pytest.fixture(scope="module", autouse=True)
async def ensure_demo_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def release_database_pool_after_test() -> None:
    yield
    await engine.dispose()


async def demo_request(payload: dict[str, object]):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.post("/demo-api/proxy", json=payload)


@pytest.mark.asyncio
async def test_demo_page_and_assets_are_available() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        page = await client.get("/demo/")
        script = await client.get("/demo/app.js")
        stylesheet = await client.get("/demo/styles.css")

    assert page.status_code == 200
    assert "采购流程体验台" in page.text
    assert "新建采购申请" in page.text
    assert "管辖楼宇全部申请" in page.text
    assert script.status_code == 200
    assert "保存草稿" in script.text
    assert "保存审核资料" in script.text
    assert "保存采购信息" in script.text
    assert "保存入库信息" in script.text
    assert 'data-tab="assistant"' in page.text
    assert 'id="assistant-form"' in page.text
    assert 'id="assistant-result"' in page.text
    assert '"/demo-api/agent-chat"' in script.text
    assert "执行详情" in script.text
    assert "Trace 时间线" in script.text
    assert "本次未调用模型" in script.text
    assert 'state.role.kind !== "applicant"' in script.text
    for device_type in (
        "电气",
        "暖通",
        "弱电",
        "机房环境",
        "工器具",
        "算力服务器",
        "IDC网络",
        "其他",
    ):
        assert device_type in script.text
    assert stylesheet.status_code == 200


@pytest.mark.asyncio
async def test_demo_proxy_uses_normal_identity_and_permissions() -> None:
    identity = await demo_request(
        {
            "platform_user_id": "test-user-01",
            "method": "GET",
            "path": "/api/v1/users/me",
        }
    )
    forbidden = await demo_request(
        {
            "platform_user_id": "test-user-01",
            "method": "GET",
            "path": "/api/v1/notifications",
        }
    )

    assert identity.status_code == 200
    assert identity.json()["data"]["employee_id"] == 90001
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_demo_proxy_rejects_unknown_users_and_unsafe_paths() -> None:
    unknown_user = await demo_request(
        {
            "platform_user_id": "someone-else",
            "method": "GET",
            "path": "/api/v1/users/me",
        }
    )
    unsafe_path = await demo_request(
        {
            "platform_user_id": "test-user-01",
            "method": "GET",
            "path": "/api/v1/../openapi.json",
        }
    )

    assert unknown_user.status_code == 403
    assert unknown_user.json()["code"] == "DEMO_USER_NOT_ALLOWED"
    assert unsafe_path.status_code == 422
    assert unsafe_path.json()["code"] == "DEMO_PATH_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_demo_agent_chat_forwards_only_allowlisted_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_forward(
        payload: DemoAgentChatRequest,
        trace_id: str,
    ) -> tuple[int, dict]:
        captured["payload"] = payload
        captured["trace_id"] = trace_id
        return 200, {
            "success": True,
            "code": "OK",
            "message": "请求成功",
            "data": {
                "conversation_id": "conversation-demo",
                "message_id": "message-demo",
                "task_id": "task-demo",
                "task_type": "ANALYSIS",
                "status": "ACCEPTED",
                "summary": "查询完成",
                "result": {"result_kind": "ANALYSIS", "completion_status": "COMPLETE"},
            },
            "trace_id": "trace-agent",
        }

    monkeypatch.setattr(demo_route, "forward_agent_chat", fake_forward)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/demo-api/agent-chat",
            json={
                "platform_user_id": "test-user-02",
                "message": "统计本月服务器采购金额",
                "external_conversation_id": "browser-conversation",
                "external_message_id": "browser-message",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["task_type"] == "ANALYSIS"
    forwarded = captured["payload"]
    assert isinstance(forwarded, DemoAgentChatRequest)
    assert forwarded.platform_user_id == "test-user-02"
    assert forwarded.message == "统计本月服务器采购金额"
    assert isinstance(captured["trace_id"], str)
    assert captured["trace_id"]


@pytest.mark.asyncio
async def test_demo_agent_chat_rejects_unknown_user_before_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_forward(
        payload: DemoAgentChatRequest,
        trace_id: str,
    ) -> tuple[int, dict]:
        nonlocal called
        called = True
        return 200, {}

    monkeypatch.setattr(demo_route, "forward_agent_chat", fake_forward)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/demo-api/agent-chat",
            json={
                "platform_user_id": "external-user",
                "message": "查询采购数据",
            },
        )

    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_USER_NOT_ALLOWED"
    assert called is False


@pytest.mark.asyncio
async def test_demo_agent_action_forwards_only_confirm_or_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_forward(payload, action: str, trace_id: str) -> tuple[int, dict]:
        captured.update(payload=payload, action=action, trace_id=trace_id)
        return 200, {"success": True, "data": {"status": "CANCELED"}}

    monkeypatch.setattr(demo_route, "forward_agent_action", fake_forward)
    body = {
        "platform_user_id": "test-user-01",
        "conversation_id": 41,
        "action_id": "a" * 32,
        "confirmation_token": "t" * 32,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/demo-api/agent-actions/cancel", json=body)
        forbidden = await client.post("/demo-api/agent-actions/execute-anything", json=body)

    assert response.status_code == 200
    assert forbidden.status_code == 404
    assert captured["action"] == "cancel"
    assert isinstance(captured["payload"], DemoAgentActionRequest)


def test_frontend_does_not_contain_gateway_credentials() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    combined_source = "\n".join(
        path.read_text(encoding="utf-8") for path in frontend.iterdir() if path.is_file()
    )

    assert "IDENTITY_GATEWAY_SECRET" not in combined_source
    assert "X-Gateway-Signature" not in combined_source
    assert "MODEL_API_KEY" not in combined_source


def test_frontend_contains_rag_trace_and_hitl_controls() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    app_source = (frontend / "app.js").read_text(encoding="utf-8")
    html_source = (frontend / "index.html").read_text(encoding="utf-8")

    assert "renderKnowledgeResult" in app_source
    assert "检索 Trace" in app_source
    assert 'data-hitl="confirm"' in app_source
    assert 'data-hitl="cancel"' in app_source
    assert "/demo-api/agent-actions/" in app_source
    assert "正式动作需人工确认" in html_source
