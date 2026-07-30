from __future__ import annotations

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.docker"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def generated_password() -> str:
    return secrets.token_urlsafe(32)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--rotate",
    action="store_true",
    help="Regenerate all local Docker passwords without printing them.",
)
args = parser.parse_args()

values = read_env(ENV_PATH)
defaults = {
    "APP_NAME": "Procurement Agent",
    "APP_ENV": "development",
    "DEBUG": "true",
    "API_V1_PREFIX": "/api/v1",
    "LOG_LEVEL": "INFO",
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": "3307",
    "MYSQL_DATABASE": "procurement_agent",
    "MYSQL_USER": "procurement_agent_app",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6380",
    "REDIS_DB": "0",
    "IDENTITY_SIGNATURE_TTL_SECONDS": "300",
    "IDENTITY_NONCE_TTL_SECONDS": "300",
}
for key, value in defaults.items():
    values[key] = value

for secret_key in (
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "REDIS_PASSWORD",
    "IDENTITY_GATEWAY_SECRET",
):
    if args.rotate or secret_key not in values:
        values[secret_key] = generated_password()

ordered_keys = [
    "APP_NAME",
    "APP_ENV",
    "DEBUG",
    "API_V1_PREFIX",
    "LOG_LEVEL",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "REDIS_DB",
    "IDENTITY_GATEWAY_SECRET",
    "IDENTITY_SIGNATURE_TTL_SECONDS",
    "IDENTITY_NONCE_TTL_SECONDS",
]
content = "\n".join(f"{key}={values[key]}" for key in ordered_keys) + "\n"
temporary_path = ENV_PATH.with_suffix(".docker.tmp")
temporary_path.write_text(content, encoding="utf-8")
temporary_path.replace(ENV_PATH)

print("Updated .env.docker with isolated project settings.")
print("Secret values were generated locally and were not printed.")
