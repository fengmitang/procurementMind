import hashlib
import hmac
import time
from collections.abc import Callable
from uuid import uuid4

from agent_app.schemas.backend import BackendIdentity

PLATFORM_HEADER = "X-Platform-Type"
USER_HEADER = "X-Platform-User-Id"
TIMESTAMP_HEADER = "X-Gateway-Timestamp"
NONCE_HEADER = "X-Gateway-Nonce"
SIGNATURE_HEADER = "X-Gateway-Signature"
REQUEST_ID_HEADER = "X-Request-Id"


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


class GatewaySigner:
    def __init__(
        self,
        secret: str,
        *,
        time_provider: Callable[[], float] = time.time,
        nonce_provider: Callable[[], str] | None = None,
    ) -> None:
        self._secret = secret
        self._time_provider = time_provider
        self._nonce_provider = nonce_provider or (lambda: uuid4().hex)

    def signed_headers(
        self,
        method: str,
        path: str,
        identity: BackendIdentity,
        trace_id: str,
    ) -> dict[str, str]:
        timestamp = str(int(self._time_provider()))
        nonce = self._nonce_provider()
        signature = build_gateway_signature(
            secret=self._secret,
            method=method,
            path=path,
            platform_type=identity.platform_type,
            platform_user_id=identity.platform_user_id,
            timestamp=timestamp,
            nonce=nonce,
        )
        return {
            PLATFORM_HEADER: identity.platform_type,
            USER_HEADER: identity.platform_user_id,
            TIMESTAMP_HEADER: timestamp,
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: signature,
            REQUEST_ID_HEADER: trace_id,
        }
