from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.docker"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Procurement Agent"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 13307
    mysql_database: str = "procurement_mind"
    mysql_user: str = "procurement_mind_app"
    mysql_password: str = Field(repr=False)

    redis_host: str = "127.0.0.1"
    redis_port: int = 16380
    redis_password: str = Field(repr=False)
    redis_db: int = 0
    agent_session_ttl_seconds: int = 259200

    identity_gateway_secret: str = Field(repr=False)
    identity_signature_ttl_seconds: int = 300
    identity_nonce_ttl_seconds: int = 300

    notification_gateway_url: str | None = None
    notification_gateway_token: str | None = Field(default=None, repr=False)
    notification_request_timeout_seconds: float = 10.0
    notification_max_retries: int = 5
    notification_retry_base_seconds: int = 60
    notification_retry_max_seconds: int = 86400
    notification_worker_batch_size: int = 50

    analytics_query_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    analytics_max_scan_rows: int = Field(default=5000, ge=100, le=50000)
    analytics_default_range_days: int = Field(default=365, ge=30, le=1095)
    risk_duplicate_window_days: int = Field(default=30, ge=1, le=365)
    risk_price_deviation_ratio: float = Field(default=0.2, ge=0.01, le=5)
    risk_quantity_deviation_ratio: float = Field(default=0.5, ge=0.01, le=5)
    risk_long_pending_days: int = Field(default=14, ge=1, le=365)

    agent_service_url: str = "http://127.0.0.1:8100"
    agent_service_timeout_seconds: float = Field(default=130.0, gt=0, le=1800)

    @property
    def database_url(self) -> str:
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+asyncmy://{self.mysql_user}:{password}@"
            f"{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        password = quote_plus(self.redis_password)
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
