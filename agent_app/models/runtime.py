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
    READY = "READY"
    PROVIDER_NOT_REGISTERED = "PROVIDER_NOT_REGISTERED"


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
        adapter = registry.build(configuration)
        return cls(
            configuration=configuration,
            status=ModelRuntimeStatus.READY,
            runner=StructuredModelRunner(
                adapter,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=settings.model_structured_output_retries,
                circuit_breaker=AsyncCircuitBreaker(
                    failure_threshold=settings.model_circuit_failure_threshold,
                    recovery_timeout_seconds=(settings.model_circuit_recovery_timeout_seconds),
                ),
                usage_ledger=ledger,
            ),
            usage_ledger=ledger,
        )

    def require_runner(self) -> StructuredModelRunner:
        if self.runner is None:
            messages = {
                ModelRuntimeStatus.NOT_CONFIGURED: "生成模型尚未配置",
                ModelRuntimeStatus.PROVIDER_NOT_REGISTERED: "生成模型供应商适配器尚未注册",
            }
            raise ModelRuntimeUnavailable(self.status, messages[self.status])
        return self.runner
