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


def read_frontend_source() -> str:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (frontend / "src").rglob("*")
        if path.suffix in {".ts", ".tsx", ".css"}
    )


@pytest.mark.asyncio
async def test_demo_page_and_assets_are_available() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        page = await client.get("/demo/")

    assert page.status_code == 200
    assert "采购智能协同平台" in page.text
    app_source = read_frontend_source()
    assert "新建采购申请" in app_source
    assert "楼宇采购记录" in app_source
    assert "保存草稿" in app_source
    assert "填写审批方案" in app_source
    assert "登记采购结果" in app_source
    assert "登记入库" in app_source
    assert "'/demo-api/agent-chat'" in app_source
    for device_type in (
        "10kV开关柜",
        "变压器",
        "400V配电柜",
        "UPS",
        "高压直流",
        "蓄电池",
        "监控",
        "冷水机组",
        "SHU",
        "冷却塔",
        "冷却泵",
        "机房环境",
        "水系统",
        "传输",
        "服务器",
        "运维工具",
        "列间空调",
    ):
        assert device_type in app_source


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


def test_demo_identity_resolver_distinguishes_test_and_full_demo_users() -> None:
    test_identity = demo_route.resolve_demo_identity("test-user-01")
    demo_identity = demo_route.resolve_demo_identity("demo_user_001")

    assert test_identity.platform_type == "TEST_PLATFORM"
    assert demo_identity.platform_type == "WEB"
    assert demo_identity.platform_user_id == "demo_user_001"


@pytest.mark.parametrize("platform_user_id", ["demo_user_999", "random-user", "test-user-99"])
def test_demo_identity_resolver_rejects_unknown_users(platform_user_id: str) -> None:
    with pytest.raises(Exception) as exc_info:
        demo_route.resolve_demo_identity(platform_user_id)

    assert getattr(exc_info.value, "code", None) == "DEMO_USER_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_demo_proxy_signs_full_demo_user_as_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    original_signer = demo_route.build_gateway_signature

    def capture_signature(**kwargs):
        captured["platform_type"] = kwargs["platform_type"]
        captured["platform_user_id"] = kwargs["platform_user_id"]
        return original_signer(**kwargs)

    monkeypatch.setattr(demo_route, "build_gateway_signature", capture_signature)
    await demo_request(
        {
            "platform_user_id": "demo_user_001",
            "method": "GET",
            "path": "/api/v1/users/me",
        }
    )

    assert captured == {
        "platform_type": "WEB",
        "platform_user_id": "demo_user_001",
    }


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
        identity: demo_route.DemoIdentity,
        trace_id: str,
    ) -> tuple[int, dict]:
        captured["payload"] = payload
        captured["identity"] = identity
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
    assert captured["identity"].platform_type == "TEST_PLATFORM"
    assert isinstance(captured["trace_id"], str)
    assert captured["trace_id"]


@pytest.mark.asyncio
async def test_demo_agent_chat_rejects_unknown_user_before_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_forward(
        payload: DemoAgentChatRequest,
        identity: demo_route.DemoIdentity,
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

    async def fake_forward(payload, identity, action: str, trace_id: str) -> tuple[int, dict]:
        captured.update(payload=payload, identity=identity, action=action, trace_id=trace_id)
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
    assert captured["identity"].platform_type == "TEST_PLATFORM"


@pytest.mark.asyncio
async def test_demo_agent_chat_and_actions_forward_web_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[demo_route.DemoIdentity] = []

    async def fake_chat(payload, identity, trace_id):
        captured.append(identity)
        return 200, {"success": True, "data": {"status": "ACCEPTED"}}

    async def fake_action(payload, identity, action, trace_id):
        captured.append(identity)
        return 200, {"success": True, "data": {"status": "CONFIRMED"}}

    monkeypatch.setattr(demo_route, "forward_agent_chat", fake_chat)
    monkeypatch.setattr(demo_route, "forward_agent_action", fake_action)
    action_body = {
        "platform_user_id": "demo_user_001",
        "conversation_id": 41,
        "action_id": "a" * 32,
        "confirmation_token": "t" * 32,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        chat = await client.post(
            "/demo-api/agent-chat",
            json={"platform_user_id": "demo_user_001", "message": "查询采购数据"},
        )
        confirm = await client.post("/demo-api/agent-actions/confirm", json=action_body)
        cancel = await client.post("/demo-api/agent-actions/cancel", json=action_body)

    assert chat.status_code == confirm.status_code == cancel.status_code == 200
    assert [identity.platform_type for identity in captured] == ["WEB", "WEB", "WEB"]


def test_agent_payload_builders_use_resolved_web_identity_for_chat_stream_and_actions() -> None:
    identity = demo_route.resolve_demo_identity("demo_user_002")
    chat = DemoAgentChatRequest(platform_user_id="demo_user_002", message="推荐供应商")
    action = DemoAgentActionRequest(
        platform_user_id="demo_user_002",
        conversation_id=41,
        action_id="a" * 32,
        confirmation_token="t" * 32,
    )

    assert demo_route.build_agent_chat_payload(chat, identity)["platform_type"] == "WEB"
    assert demo_route.build_agent_action_payload(action, identity)["platform_type"] == "WEB"


@pytest.mark.asyncio
async def test_demo_agent_stream_forwards_web_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeUpstream:
        is_error = False
        status_code = 200

        async def aiter_bytes(self):
            yield b'event: completed\ndata: {"success": true}\n\n'

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeUpstream()

        async def __aexit__(self, *_):
            return None

    class FakeAgentClient:
        def __init__(self, **_):
            pass

        def stream(self, method, path, **kwargs):
            captured.update(method=method, path=path, json=kwargs["json"])
            return FakeStreamContext()

        async def aclose(self):
            return None

    monkeypatch.setattr(demo_route, "AsyncClient", FakeAgentClient)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/demo-api/agent-chat/stream",
            json={"platform_user_id": "demo_user_002", "message": "推荐供应商"},
        )

    assert response.status_code == 200
    assert captured["json"]["platform_type"] == "WEB"
    assert captured["json"]["platform_user_id"] == "demo_user_002"


def test_frontend_does_not_contain_gateway_credentials() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    combined_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in frontend.rglob("*")
        if path.is_file()
        and "node_modules" not in path.parts
        and "dist" not in path.parts
        and path.suffix in {".ts", ".tsx", ".js", ".json", ".html", ".css"}
    )

    assert "IDENTITY_GATEWAY_SECRET" not in combined_source
    assert "X-Gateway-Signature" not in combined_source
    assert "MODEL_API_KEY" not in combined_source


def test_frontend_contains_rag_sources_and_hitl_controls() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    assistant_source = (frontend / "src/pages/assistant/AssistantPage.tsx").read_text(
        encoding="utf-8"
    )
    agent_client_source = (frontend / "src/services/agentClient.ts").read_text(encoding="utf-8")

    assert "Sources" in assistant_source
    assert "knowledge_sources" in assistant_source
    assert "source_path" not in assistant_source
    assert "确认执行" in assistant_source
    assert "取消" in assistant_source
    assert "/demo-api/agent-actions/" in agent_client_source
    assert "trace_events" not in assistant_source
