from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_runs_as_non_root_and_does_not_copy_environment_files() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER procurement" in dockerfile
    assert "--uid 10001" in dockerfile
    assert "COPY . " not in dockerfile
    assert "COPY .env" not in dockerfile
    assert "MODEL_API_KEY" not in dockerfile
    assert "MYSQL_PASSWORD" not in dockerfile
    assert "REDIS_PASSWORD" not in dockerfile


def test_docker_build_context_excludes_local_secrets_and_state() -> None:
    ignore_entries = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".env" in ignore_entries
    assert ".env.*" in ignore_entries
    assert ".data" in ignore_entries
    assert ".git" in ignore_entries


def test_compose_keeps_application_ports_local_and_secrets_runtime_only() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    for service in ("migrate", "backend", "agent"):
        assert f"  {service}:" in compose

    assert '"127.0.0.1:${BACKEND_PORT:-8000}:8000"' in compose
    assert '"127.0.0.1:${AGENT_PORT:-8100}:8100"' in compose
    assert "PROCUREMENT_BACKEND_URL: http://backend:8000" in compose
    assert "AGENT_SERVICE_URL: http://agent:8100" in compose
    assert "IDENTITY_GATEWAY_SECRET: ${IDENTITY_GATEWAY_SECRET:" in compose
    assert "MODEL_API_KEY: ${MODEL_API_KEY:-}" in compose
    assert "USER procurement" not in compose
