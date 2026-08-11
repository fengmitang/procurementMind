from collections.abc import Callable

from agent_app.models.configuration import ModelRuntimeConfiguration
from agent_app.models.protocols import StructuredModelAdapter

AdapterFactory = Callable[[ModelRuntimeConfiguration], StructuredModelAdapter]


class ModelAdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, provider: str, factory: AdapterFactory) -> None:
        normalized = provider.strip().lower()
        if not normalized:
            raise ValueError("模型供应商标识不能为空")
        if normalized in self._factories:
            raise ValueError(f"模型供应商适配器已注册：{normalized}")
        self._factories[normalized] = factory

    def build(self, configuration: ModelRuntimeConfiguration) -> StructuredModelAdapter:
        if not configuration.configured or not configuration.provider:
            raise ValueError("模型配置尚未完成")
        provider = configuration.provider.strip().lower()
        factory = self._factories.get(provider)
        if factory is None:
            raise ValueError(f"尚未注册模型供应商适配器：{provider}")
        return factory(configuration)

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def build_default_model_registry() -> ModelAdapterRegistry:
    from agent_app.models.openai_compatible import OpenAICompatibleStructuredAdapter

    registry = ModelAdapterRegistry()
    registry.register("openai_compatible", OpenAICompatibleStructuredAdapter)
    return registry
