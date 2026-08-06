from pydantic import BaseModel, ConfigDict, SecretStr

from agent_app.core.config import AgentSettings


class ModelRuntimeConfiguration(BaseModel):
    """Provider-neutral model settings; provider SDKs are added only after selection."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None
    model: str | None
    fallback_model: str | None
    api_key: SecretStr | None
    base_url: str | None
    configured: bool

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "ModelRuntimeConfiguration":
        return cls(
            provider=settings.model_provider,
            model=settings.primary_model,
            fallback_model=settings.fallback_model,
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
            configured=settings.model_configured,
        )
