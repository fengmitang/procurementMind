import hashlib
import hmac
import re
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from starlette.requests import Request

from app.core.config import Settings
from app.core.exceptions import AppError

PLATFORM_HEADER = "X-Platform-Type"
USER_HEADER = "X-Platform-User-Id"
TIMESTAMP_HEADER = "X-Gateway-Timestamp"
NONCE_HEADER = "X-Gateway-Nonce"
SIGNATURE_HEADER = "X-Gateway-Signature"

SUPPORTED_PLATFORMS = {"FEISHU", "DINGTALK", "WECHAT_WORK", "WEB"}
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True, slots=True)
class GatewayIdentity:
    platform_type: str
    platform_user_id: str


def build_gateway_signature(
    *,
    secret: str,
    method: str,
    path: str,
    platform_type: str,
    platform_user_id: str,
    timestamp: str,
    nonce: str,
) -> str:
    canonical = "\n".join(
        (
            method.upper(),
            path,
            platform_type,
            platform_user_id,
            timestamp,
            nonce,
        )
    )
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _required_header(request: Request, name: str) -> str:
    value = request.headers.get(name)
    if not value:
        raise AppError("IDENTITY_REQUIRED", f"缺少身份请求头 {name}", 401)
    return value


async def verify_gateway_identity(
    request: Request,
    settings: Settings,
) -> GatewayIdentity:
    platform_type = _required_header(request, PLATFORM_HEADER).upper()
    platform_user_id = _required_header(request, USER_HEADER)
    timestamp = _required_header(request, TIMESTAMP_HEADER)
    nonce = _required_header(request, NONCE_HEADER)
    supplied_signature = _required_header(request, SIGNATURE_HEADER).lower()

    allowed_platforms = set(SUPPORTED_PLATFORMS)
    if settings.app_env.lower() != "production":
        allowed_platforms.add("TEST_PLATFORM")
    if platform_type not in allowed_platforms:
        raise AppError("UNSUPPORTED_PLATFORM", "不支持的平台类型", 400)
    if len(platform_user_id) > 150:
        raise AppError("INVALID_IDENTITY", "平台用户标识格式不正确", 400)
    if not NONCE_PATTERN.fullmatch(nonce):
        raise AppError("INVALID_IDENTITY", "网关随机数格式不正确", 400)

    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise AppError("INVALID_IDENTITY", "网关时间戳格式不正确", 400) from exc
    if abs(int(time.time()) - timestamp_value) > settings.identity_signature_ttl_seconds:
        raise AppError("IDENTITY_SIGNATURE_EXPIRED", "网关身份签名已过期", 401)

    expected_signature = build_gateway_signature(
        secret=settings.identity_gateway_secret,
        method=request.method,
        path=request.url.path,
        platform_type=platform_type,
        platform_user_id=platform_user_id,
        timestamp=timestamp,
        nonce=nonce,
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise AppError("INVALID_IDENTITY_SIGNATURE", "网关身份签名无效", 401)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        accepted = await redis.set(
            f"identity:nonce:{platform_type}:{nonce}",
            "1",
            ex=settings.identity_nonce_ttl_seconds,
            nx=True,
        )
    except Exception as exc:
        raise AppError("IDENTITY_SERVICE_UNAVAILABLE", "身份校验服务暂不可用", 503) from exc
    finally:
        await redis.aclose()
    if not accepted:
        raise AppError("IDENTITY_REPLAYED", "网关身份请求已使用", 401)

    return GatewayIdentity(
        platform_type=platform_type,
        platform_user_id=platform_user_id,
    )
