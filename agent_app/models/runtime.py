from dataclasses import dataclass
from enum import StrEnum

from agent_app.core.config import AgentSettings
from agent_app.models.configuration import ModelRuntimeConfiguration
from agent_app.models.registry import ModelAdapterRegistry
from agent_app.models.runner import StructuredModelRunner
from agent_app.models.usage import ModelUsageLedger
from agent_app.resilience import AsyncCircuitBreaker


class ModelRuntimeStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    PROVIDER_NOT_REGISTERED = "PROVIDER_NOT_REGISTERED"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"


class ModelRuntimeUnavailable(RuntimeError):
    def __init__(self, status: ModelRuntimeStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(slots=True)
class ModelRuntime:
    configuration: ModelRuntimeConfiguration
    status: ModelRuntimeStatus
    runner: StructuredModelRunner | None
    usage_ledger: ModelUsageLedger
    initialization_error: str | None = None

    @classmethod
    def from_settings(
        cls,
        settings: AgentSettings,
        registry: ModelAdapterRegistry,
    ) -> "ModelRuntime":
        configuration = ModelRuntimeConfiguration.from_settings(settings)
        ledger = ModelUsageLedger()
        if not configuration.configured:
            return cls(
                configuration=configuration,
                status=ModelRuntimeStatus.NOT_CONFIGURED,
                runner=None,
                usage_ledger=ledger,
            )
        assert configuration.provider is not None
        if configuration.provider.strip().lower() not in registry.providers:
            return cls(
                configuration=configuration,
                status=ModelRuntimeStatus.PROVIDER_NOT_REGISTERED,
                runner=None,
                usage_ledger=ledger,
            )
        try:
            primary_adapter = registry.build(
                configuration.model_copy(update={"fallback_model": None})
            )
            fallback_adapter = None
            if configuration.fallback_model:
                fallback_adapter = registry.build(
                    configuration.model_copy(
                        update={
                            "model": configuration.fallback_model,
                            "fallback_model": None,
                        }
                    )
                )
        except Exception as exc:
            return cls(
                configuration=configuration,
                status=ModelRuntimeStatus.INITIALIZATION_FAILED,
                runner=None,
                usage_ledger=ledger,
                initialization_error=f"{type(exc).__name__}: {exc}",
            )
        return cls(
            configuration=configuration,
            status=ModelRuntimeStatus.READY,
            runner=StructuredModelRunner(
                primary_adapter,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=settings.model_structured_output_retries,
                circuit_breaker=AsyncCircuitBreaker(
                    failure_threshold=settings.model_circuit_failure_threshold,
                    recovery_timeout_seconds=settings.model_circuit_recovery_timeout_seconds,
                ),
                usage_ledger=ledger,
                fallback_adapter=fallback_adapter,
                primary_model=configuration.model,
            ),
            usage_ledger=ledger,
        )

    async def aclose(self) -> None:
        if self.runner is not None:
            await self.runner.aclose()

    def require_runner(self) -> StructuredModelRunner:
        if self.runner is None:
            messages = {
                ModelRuntimeStatus.NOT_CONFIGURED: "生成模型尚未配置",
                ModelRuntimeStatus.INITIALIZING: "生成模型正在初始化",
                ModelRuntimeStatus.PROVIDER_NOT_REGISTERED: "生成模型 Provider 尚未注册",
                ModelRuntimeStatus.INITIALIZATION_FAILED: "生成模型初始化失败",
            }
            raise ModelRuntimeUnavailable(self.status, messages[self.status])
        return self.runner
