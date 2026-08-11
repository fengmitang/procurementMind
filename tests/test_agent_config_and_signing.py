import pytest
from pydantic import ValidationError

from agent_app.clients.signing import GatewaySigner, build_gateway_signature
from agent_app.core.config import AgentSettings
from agent_app.schemas.backend import BackendIdentity
from agent_app.schemas.chat import ChatRequest
from app.core.gateway_auth import build_gateway_signature as backend_signature

TEST_SECRET = "test-agent-gateway-secret-value"


def test_agent_settings_normalize_backend_url_and_hide_secret() -> None:
    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret=TEST_SECRET,
        procurement_backend_url="http://backend.local/",
    )

    assert settings.procurement_backend_url == "http://backend.local"
    assert settings.agent_port == 8100
    assert TEST_SECRET not in repr(settings)


def test_agent_settings_reject_invalid_backend_url() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(
            _env_file=None,
            identity_gateway_secret=TEST_SECRET,
            procurement_backend_url="backend.local",
        )


def test_agent_signature_matches_procurement_backend_algorithm() -> None:
    arguments = {
        "secret": TEST_SECRET,
        "method": "get",
        "path": "/api/v1/users/me",
        "platform_type": "TEST_PLATFORM",
        "platform_user_id": "test-user-01",
        "timestamp": "1785816000",
        "nonce": "fixed_nonce_1234567890",
    }

    assert build_gateway_signature(**arguments) == backend_signature(**arguments)


def test_gateway_signer_builds_identity_and_trace_headers() -> None:
    signer = GatewaySigner(
        TEST_SECRET,
        time_provider=lambda: 1785816000,
        nonce_provider=lambda: "fixed_nonce_1234567890",
    )
    identity = BackendIdentity(
        platform_type="test_platform",
        platform_user_id="test-user-01",
    )

    headers = signer.signed_headers(
        "GET",
        "/api/v1/users/me",
        identity,
        "trace-agent-001",
    )

    assert headers["X-Platform-Type"] == "TEST_PLATFORM"
    assert headers["X-Platform-User-Id"] == "test-user-01"
    assert headers["X-Gateway-Timestamp"] == "1785816000"
    assert headers["X-Gateway-Nonce"] == "fixed_nonce_1234567890"
    assert headers["X-Request-Id"] == "trace-agent-001"
    assert headers["X-Gateway-Signature"] == backend_signature(
        secret=TEST_SECRET,
        method="GET",
        path="/api/v1/users/me",
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
        timestamp="1785816000",
        nonce="fixed_nonce_1234567890",
    )


def test_chat_request_forbids_client_reported_roles() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "platform_user_id": "test-user-01",
                "message": "查询采购单",
                "roles": ["ADMIN"],
            }
        )
