from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EmbeddingProvider(Protocol):
    @property
    def embedding_cache_identity(self) -> str: ...

    def encode_dense(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]: ...


class RerankProvider(Protocol):
    @property
    def reranker_cache_identity(self) -> str: ...

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool = True,
        batch_size: int = 4,
    ) -> list[float]: ...


@dataclass
class RAGProviders:
    """Provider-neutral facade used by indexing and online retrieval."""

    embedding_provider: EmbeddingProvider
    rerank_provider: RerankProvider

    @property
    def embedding_cache_identity(self) -> str:
        return self.embedding_provider.embedding_cache_identity

    @property
    def reranker_cache_identity(self) -> str:
        return self.rerank_provider.reranker_cache_identity

    def encode_dense(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]:
        return self.embedding_provider.encode_dense(
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
        return self.rerank_provider.rerank(
            query,
            documents,
            normalize=normalize,
            batch_size=batch_size,
        )

    def close(self) -> None:
        closed: set[int] = set()
        for provider in (self.embedding_provider, self.rerank_provider):
            if id(provider) in closed:
                continue
            closed.add(id(provider))
            close = getattr(provider, "close", None)
            if callable(close):
                close()
