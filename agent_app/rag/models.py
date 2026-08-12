from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from agent_app.rag._local import (
    LocalRAGModelError,
    RAGDevice,
    ResolvedRAGDevice,
    resolve_rag_device,
)
from agent_app.rag.embedding import BGEEmbeddingModel
from agent_app.rag.providers import RAGProviders
from agent_app.rag.reranker import BGERerankerModel

if TYPE_CHECKING:
    from agent_app.core.config import AgentSettings


class LocalRAGModels:
    """Stable process-local facade over the two device-aware BGE adapters."""

    def __init__(
        self,
        embedding_model_path: Path,
        reranker_model_path: Path,
        configured_device: RAGDevice,
    ) -> None:
        self.configured_device = configured_device
        self.device: ResolvedRAGDevice = resolve_rag_device(configured_device)
        self.embedding = BGEEmbeddingModel(embedding_model_path, self.device)
        self.reranker_model = BGERerankerModel(reranker_model_path, self.device)

    @property
    def embedding_model_path(self) -> Path:
        return self.embedding.model_path

    @property
    def reranker_model_path(self) -> Path:
        return self.reranker_model.model_path

    @property
    def initialized(self) -> bool:
        return self.embedding.initialized and self.reranker_model.initialized

    @property
    def embedding_cache_identity(self) -> str:
        return self.embedding.embedding_cache_identity

    @property
    def reranker_cache_identity(self) -> str:
        return self.reranker_model.reranker_cache_identity

    def initialize(self) -> LocalRAGModels:
        self.embedding.initialize()
        self.reranker_model.initialize()
        return self

    def encode_dense(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]:
        return self.embedding.encode(
            texts,
            batch_size=batch_size,
            max_length=max_length,
        )

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool = True,
        batch_size: int = 4,
    ) -> list[float]:
        return self.reranker_model.score(
            query,
            documents,
            normalize=normalize,
            batch_size=batch_size,
        )


@lru_cache(maxsize=4)
def get_local_rag_models(
    embedding_model_path: str,
    reranker_model_path: str,
    device: RAGDevice,
) -> LocalRAGModels:
    return LocalRAGModels(
        Path(embedding_model_path),
        Path(reranker_model_path),
        device,
    )


def initialize_local_rag_models(settings: AgentSettings) -> LocalRAGModels | None:
    if bool(settings.embedding_model_path) != bool(settings.reranker_model_path):
        raise LocalRAGModelError("EMBEDDING_MODEL_PATH 和 RERANKER_MODEL_PATH 必须同时配置")
    if not settings.rag_models_configured:
        return None
    assert settings.embedding_model_path is not None
    assert settings.reranker_model_path is not None
    if settings.rag_model_device in {"auto", "cpu"}:
        import torch

        if settings.rag_model_device == "cpu" or not torch.cuda.is_available():
            torch.set_num_threads(settings.rag_cpu_threads)
    return get_local_rag_models(
        str(settings.embedding_model_path.resolve()),
        str(settings.reranker_model_path.resolve()),
        settings.rag_model_device,
    ).initialize()


def initialize_rag_providers(settings: AgentSettings) -> RAGProviders | None:
    """Build independently selectable Embedding and Rerank providers."""

    if not settings.rag_models_configured:
        return None
    local_device: ResolvedRAGDevice | None = None

    def resolved_local_device() -> ResolvedRAGDevice:
        nonlocal local_device
        if local_device is None:
            local_device = resolve_rag_device(settings.rag_model_device)
            if local_device == "cpu":
                import torch

                torch.set_num_threads(settings.rag_cpu_threads)
        return local_device

    if settings.rag_embedding_provider == "local_bge":
        assert settings.embedding_model_path is not None
        embedding_provider = BGEEmbeddingModel(
            settings.embedding_model_path,
            resolved_local_device(),
        ).initialize()
    else:
        from agent_app.rag.aliyun_bailian import BailianEmbeddingProvider

        assert settings.resolved_rag_api_key is not None
        assert settings.resolved_rag_bailian_base_url is not None
        embedding_provider = BailianEmbeddingProvider(
            api_key=settings.resolved_rag_api_key.get_secret_value(),
            base_url=settings.resolved_rag_bailian_base_url,
            model=settings.rag_embedding_model,
            dimension=settings.rag_dense_vector_size,
            timeout_seconds=settings.rag_api_timeout_seconds,
            max_retries=settings.rag_api_max_retries,
            retry_base_seconds=settings.rag_api_retry_base_seconds,
        )

    if settings.rag_rerank_provider == "local_bge":
        assert settings.reranker_model_path is not None
        rerank_provider = BGERerankerModel(
            settings.reranker_model_path,
            resolved_local_device(),
        ).initialize()
    else:
        from agent_app.rag.aliyun_bailian import BailianRerankProvider

        assert settings.resolved_rag_api_key is not None
        assert settings.resolved_rag_bailian_base_url is not None
        rerank_provider = BailianRerankProvider(
            api_key=settings.resolved_rag_api_key.get_secret_value(),
            base_url=settings.resolved_rag_bailian_base_url,
            model=settings.rag_rerank_model,
            timeout_seconds=settings.rag_api_timeout_seconds,
            max_retries=settings.rag_api_max_retries,
            retry_base_seconds=settings.rag_api_retry_base_seconds,
            instruct=settings.rag_rerank_instruct,
        )
    return RAGProviders(
        embedding_provider=embedding_provider,
        rerank_provider=rerank_provider,
    )
