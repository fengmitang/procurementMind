import time
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient, HTTPError

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.gateway_auth import build_gateway_signature
from app.core.request_context import request_id_context
from app.schemas.demo import DemoAgentChatRequest, DemoProxyRequest

router = APIRouter(prefix="/demo-api", tags=["development-demo"])

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH"}
ALLOWED_TEST_USERS = {f"test-user-{index:02d}" for index in range(1, 9)}


async def forward_agent_chat(
    payload: DemoAgentChatRequest,
    trace_id: str,
) -> tuple[int, dict]:
    settings = get_settings()
    try:
        async with AsyncClient(
            base_url=settings.agent_service_url.rstrip("/"),
            timeout=settings.agent_service_timeout_seconds,
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                headers={"X-Request-Id": trace_id},
                json={
                    "platform_type": "TEST_PLATFORM",
                    "platform_user_id": payload.platform_user_id,
                    "message": payload.message,
                    "external_conversation_id": payload.external_conversation_id,
                    "external_message_id": payload.external_message_id,
                },
            )
    except HTTPError as exc:
        raise AppError(
            "AGENT_SERVICE_UNAVAILABLE",
            "Agent 服务暂时不可用，请确认 8100 服务已启动",
            503,
        ) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise AppError(
            "AGENT_SERVICE_PROTOCOL_ERROR",
            "Agent 服务返回了无效响应",
            502,
        ) from exc
    if not isinstance(body, dict):
        raise AppError(
            "AGENT_SERVICE_PROTOCOL_ERROR",
            "Agent 服务返回了无效响应",
            502,
        )
    return response.status_code, body


@router.post("/agent-chat", include_in_schema=False)
async def demo_agent_chat(payload: DemoAgentChatRequest) -> JSONResponse:
    settings = get_settings()
    if settings.app_env.lower() != "development":
        raise AppError("NOT_FOUND", "页面不存在", 404)
    if payload.platform_user_id not in ALLOWED_TEST_USERS:
        raise AppError("DEMO_USER_NOT_ALLOWED", "体验界面只允许 TEST 测试用户", 403)
    trace_id = request_id_context.get() or str(uuid4())
    status_code, body = await forward_agent_chat(payload, trace_id)
    return JSONResponse(status_code=status_code, content=body)


@router.post("/proxy", include_in_schema=False)
async def demo_proxy(
    payload: DemoProxyRequest,
    request: Request,
) -> JSONResponse:
    settings = get_settings()
    if settings.app_env.lower() != "development":
        raise AppError("NOT_FOUND", "页面不存在", 404)

    method = payload.method.upper()
    if method not in ALLOWED_METHODS:
        raise AppError("DEMO_METHOD_NOT_ALLOWED", "体验界面不允许该请求方法", 405)
    if (
        not payload.path.startswith("/api/v1/")
        or payload.path.startswith("/api/v1/demo")
        or ".." in payload.path
        or "?" in payload.path
        or "#" in payload.path
    ):
        raise AppError("DEMO_PATH_NOT_ALLOWED", "体验界面请求路径无效", 422)
    if payload.platform_user_id not in ALLOWED_TEST_USERS:
        raise AppError("DEMO_USER_NOT_ALLOWED", "体验界面只允许 TEST 测试用户", 403)

    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    platform_type = "TEST_PLATFORM"
    headers = {
        "X-Platform-Type": platform_type,
        "X-Platform-User-Id": payload.platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": nonce,
        "X-Gateway-Signature": build_gateway_signature(
            secret=settings.identity_gateway_secret,
            method=method,
            path=payload.path,
            platform_type=platform_type,
            platform_user_id=payload.platform_user_id,
            timestamp=timestamp,
            nonce=nonce,
        ),
    }
    async with AsyncClient(
        transport=ASGITransport(app=request.app),
        base_url="http://demo-internal",
    ) as client:
        response = await client.request(
            method,
            payload.path,
            params=payload.query,
            json=payload.body if method != "GET" else None,
            headers=headers,
        )
    return JSONResponse(
        status_code=response.status_code,
        content=response.json(),
    )
