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
    return get_local_rag_models(
        str(settings.embedding_model_path.resolve()),
        str(settings.reranker_model_path.resolve()),
        settings.rag_model_device,
    ).initialize()
