import json
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient, HTTPError

from app.core.config import get_settings
from app.core.development_identities import (
    DEVELOPMENT_IDENTITY_MAP,
    resolve_development_platform_type,
)
from app.core.exceptions import AppError
from app.core.gateway_auth import build_gateway_signature
from app.core.request_context import request_id_context
from app.schemas.demo import DemoAgentActionRequest, DemoAgentChatRequest, DemoProxyRequest

router = APIRouter(prefix="/demo-api", tags=["development-demo"])

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class DemoIdentity:
    platform_type: str
    platform_user_id: str


DEV_IDENTITY_MAP = DEVELOPMENT_IDENTITY_MAP


def resolve_demo_identity(platform_user_id: str) -> DemoIdentity:
    platform_type = resolve_development_platform_type(platform_user_id)
    if platform_type is None:
        raise AppError("DEMO_USER_NOT_ALLOWED", "体验界面不允许该用户", 403)
    return DemoIdentity(
        platform_type=platform_type,
        platform_user_id=platform_user_id,
    )


def build_agent_chat_payload(
    payload: DemoAgentChatRequest,
    identity: DemoIdentity,
) -> dict:
    return {
        "platform_type": identity.platform_type,
        "platform_user_id": identity.platform_user_id,
        "message": payload.message,
        "external_conversation_id": payload.external_conversation_id,
        "external_message_id": payload.external_message_id,
        "ui_context": payload.ui_context,
    }


def build_agent_action_payload(
    payload: DemoAgentActionRequest,
    identity: DemoIdentity,
) -> dict:
    return {
        "platform_type": identity.platform_type,
        "platform_user_id": identity.platform_user_id,
        "conversation_id": payload.conversation_id,
        "action_id": payload.action_id,
        "confirmation_token": payload.confirmation_token,
    }


async def forward_agent_chat(
    payload: DemoAgentChatRequest,
    identity: DemoIdentity,
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
                json=build_agent_chat_payload(payload, identity),
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


async def forward_agent_action(
    payload: DemoAgentActionRequest,
    identity: DemoIdentity,
    action: str,
    trace_id: str,
) -> tuple[int, dict]:
    settings = get_settings()
    try:
        async with AsyncClient(
            base_url=settings.agent_service_url.rstrip("/"),
            timeout=settings.agent_service_timeout_seconds,
        ) as client:
            response = await client.post(
                f"/api/v1/chat/actions/{action}",
                headers={"X-Request-Id": trace_id},
                json=build_agent_action_payload(payload, identity),
            )
    except HTTPError as exc:
        raise AppError("AGENT_SERVICE_UNAVAILABLE", "Agent 服务暂时不可用", 503) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise AppError("AGENT_SERVICE_PROTOCOL_ERROR", "Agent 服务返回了无效响应", 502) from exc
    if not isinstance(body, dict):
        raise AppError("AGENT_SERVICE_PROTOCOL_ERROR", "Agent 服务返回了无效响应", 502)
    return response.status_code, body


@router.post("/agent-chat", include_in_schema=False)
async def demo_agent_chat(payload: DemoAgentChatRequest) -> JSONResponse:
    settings = get_settings()
    if settings.app_env.lower() != "development":
        raise AppError("NOT_FOUND", "页面不存在", 404)
    identity = resolve_demo_identity(payload.platform_user_id)
    trace_id = request_id_context.get() or str(uuid4())
    status_code, body = await forward_agent_chat(payload, identity, trace_id)
    return JSONResponse(status_code=status_code, content=body)


@router.post("/agent-chat/stream", include_in_schema=False, response_model=None)
async def demo_agent_chat_stream(
    payload: DemoAgentChatRequest,
) -> JSONResponse | StreamingResponse:
    settings = get_settings()
    if settings.app_env.lower() != "development":
        raise AppError("NOT_FOUND", "页面不存在", 404)
    identity = resolve_demo_identity(payload.platform_user_id)
    trace_id = request_id_context.get() or str(uuid4())
    client = AsyncClient(
        base_url=settings.agent_service_url.rstrip("/"),
        timeout=settings.agent_service_timeout_seconds,
    )
    stream_context = client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers={"X-Request-Id": trace_id, "Accept": "text/event-stream"},
        json=build_agent_chat_payload(payload, identity),
    )
    try:
        upstream = await stream_context.__aenter__()
    except HTTPError as exc:
        await client.aclose()
        raise AppError(
            "AGENT_SERVICE_UNAVAILABLE",
            "智能助手暂时不可用，请稍后重试",
            503,
        ) from exc
    if upstream.is_error:
        raw = await upstream.aread()
        await stream_context.__aexit__(None, None, None)
        await client.aclose()
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = {
                "success": False,
                "code": "AGENT_SERVICE_PROTOCOL_ERROR",
                "message": "智能助手返回了无效响应",
                "data": None,
                "trace_id": trace_id,
            }
        return JSONResponse(status_code=upstream.status_code, content=body)

    async def forward_stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await stream_context.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        forward_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": trace_id,
        },
    )


@router.post("/agent-actions/{action}", include_in_schema=False)
async def demo_agent_action(action: str, payload: DemoAgentActionRequest) -> JSONResponse:
    settings = get_settings()
    if settings.app_env.lower() != "development":
        raise AppError("NOT_FOUND", "页面不存在", 404)
    if action not in {"confirm", "cancel"}:
        raise AppError("DEMO_ACTION_NOT_ALLOWED", "体验界面不允许该确认动作", 404)
    identity = resolve_demo_identity(payload.platform_user_id)
    trace_id = request_id_context.get() or str(uuid4())
    status_code, body = await forward_agent_action(payload, identity, action, trace_id)
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
    identity = resolve_demo_identity(payload.platform_user_id)

    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    headers = {
        "X-Platform-Type": identity.platform_type,
        "X-Platform-User-Id": identity.platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": nonce,
        "X-Gateway-Signature": build_gateway_signature(
            secret=settings.identity_gateway_secret,
            method=method,
            path=payload.path,
            platform_type=identity.platform_type,
            platform_user_id=identity.platform_user_id,
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
