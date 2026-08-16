from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from agent_app.device_terms.schemas import (
    DeviceTermLookupResult,
    DeviceTermLookupStatus,
    DeviceTermPayload,
    DeviceTermSource,
)
from agent_app.device_terms.store import QdrantDeviceTermStore
from agent_app.device_terms.text import (
    build_device_term_query,
    build_device_term_search_text,
    normalize_device_name,
)
from agent_app.rag.providers import EmbeddingProvider
from app.schemas.procurement import DeviceType


class DeviceTermIndexService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        store: QdrantDeviceTermStore,
        embedding_batch_size: int,
        embedding_max_length: int,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.store = store
        self.embedding_batch_size = embedding_batch_size
        self.embedding_max_length = embedding_max_length

    async def rebuild(self, sources: Sequence[DeviceTermSource]) -> list[DeviceTermPayload]:
        payloads = self._deduplicate(sources)
        vectors = await asyncio.to_thread(
            self.embedding_provider.encode_dense,
            [item.search_text for item in payloads],
            batch_size=self.embedding_batch_size,
            max_length=self.embedding_max_length,
        ) if payloads else []
        await self.store.recreate_collection()
        if payloads:
            await self.store.upsert_terms(payloads, vectors)
        return payloads

    @staticmethod
    def _deduplicate(sources: Sequence[DeviceTermSource]) -> list[DeviceTermPayload]:
        merged: dict[tuple[str, str], DeviceTermSource] = {}
        for source in sources:
            normalized = normalize_device_name(source.device_name)
            key = (source.device_profession, normalized)
            existing = merged.get(key)
            if existing is None:
                merged[key] = source.model_copy(update={"device_name": source.device_name.strip()})
            else:
                merged[key] = existing.model_copy(
                    update={"source_count": existing.source_count + source.source_count}
                )
        return [
            DeviceTermPayload(
                device_name=source.device_name,
                device_profession=source.device_profession,
                normalized_name=normalized,
                search_text=build_device_term_search_text(
                    source.device_name, source.device_profession
                ),
                source_count=source.source_count,
            )
            for (_, normalized), source in sorted(merged.items())
        ]


class DeviceTermSearchService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        store: QdrantDeviceTermStore,
        top_k: int = 5,
        embedding_batch_size: int = 4,
        embedding_max_length: int = 512,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.store = store
        self.top_k = top_k
        self.embedding_batch_size = embedding_batch_size
        self.embedding_max_length = embedding_max_length

    async def lookup(
        self,
        query_term: str,
        device_profession: DeviceType,
    ) -> DeviceTermLookupResult:
        started = time.perf_counter()
        qdrant_ms = 0
        embedding_ms = 0
        try:
            exact_started = time.perf_counter()
            exact = await self.store.find_exact(
                normalize_device_name(query_term), device_profession
            )
            qdrant_ms += self._elapsed_ms(exact_started)
            if exact is not None:
                return DeviceTermLookupResult(
                    status=DeviceTermLookupStatus.EXACT,
                    query_term=query_term,
                    device_profession=device_profession,
                    exact_match=True,
                    candidates=[exact],
                    top_k=self.top_k,
                    qdrant_latency_ms=qdrant_ms,
                    total_latency_ms=self._elapsed_ms(started),
                )
            query_text = build_device_term_query(query_term, device_profession)
            embedding_started = time.perf_counter()
            vectors = await asyncio.to_thread(
                self.embedding_provider.encode_dense,
                [query_text],
                batch_size=self.embedding_batch_size,
                max_length=self.embedding_max_length,
            )
            embedding_ms = self._elapsed_ms(embedding_started)
            if len(vectors) != 1:
                raise ValueError("设备术语 Query Embedding 返回数量无效")
            search_started = time.perf_counter()
            candidates = await self.store.search(
                vectors[0], device_profession, limit=self.top_k
            )
            qdrant_ms += self._elapsed_ms(search_started)
            status = (
                DeviceTermLookupStatus.SEMANTIC
                if candidates
                else DeviceTermLookupStatus.NO_MATCH
            )
            return DeviceTermLookupResult(
                status=status,
                query_term=query_term,
                device_profession=device_profession,
                semantic_used=True,
                candidates=candidates,
                top_k=self.top_k,
                embedding_latency_ms=embedding_ms,
                qdrant_latency_ms=qdrant_ms,
                total_latency_ms=self._elapsed_ms(started),
                fallback_triggered=not candidates,
                message=None if candidates else "语义索引未返回候选，保留原始结构化查询",
            )
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            return DeviceTermLookupResult(
                status=DeviceTermLookupStatus.FALLBACK,
                query_term=query_term,
                device_profession=device_profession,
                semantic_used=embedding_ms > 0,
                top_k=self.top_k,
                embedding_latency_ms=embedding_ms,
                qdrant_latency_ms=qdrant_ms,
                total_latency_ms=self._elapsed_ms(started),
                fallback_triggered=True,
                error_code=str(code),
                message="设备名称语义检索不可用，已回退到原始 Backend 查询",
            )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
