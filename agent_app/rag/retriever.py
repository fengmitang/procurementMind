from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import time
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import uuid4

from qdrant_client import models
from sqlalchemy.ext.asyncio import AsyncSession

from agent_app.core.config import AgentSettings
from agent_app.core.request_context import trace_id_context
from agent_app.performance import VersionedTTLCache
from agent_app.rag.qdrant import QdrantKnowledgeStore
from agent_app.rag.query_policy import QUERY_POLICY_VERSION, can_skip_query_rewrite, normalize_query
from agent_app.rag.schemas import (
    ChildChunkPayload,
    KnowledgeCitation,
    ParentLookupTrace,
    RerankTraceItem,
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalResult,
    RetrievalTimings,
    RetrievalTrace,
    RetrievedEvidence,
)
from app.models.knowledge import KnowledgeParent
from app.repositories.knowledge import KnowledgeRepository

_PARENT_EXPAND_TYPES = {"rule", "step", "risk", "section"}
_PARENT_QUERY_SIGNALS = ("流程", "完整", "全部", "整体", "前后", "上下文", "如何", "为什么")


class RetrievalModelProvider(Protocol):
    def encode_dense(
        self, texts: list[str], *, batch_size: int, max_length: int
    ) -> list[list[float]]: ...

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool,
        batch_size: int,
    ) -> list[float]: ...


class QueryRewriteProvider(Protocol):
    async def rewrite(self, query: str) -> str: ...


class KnowledgeRetriever:
    """Dense/BM25/RRF retrieval followed by local reranking and selective Parent lookup."""

    supports_rewrite_context = True

    def __init__(
        self,
        *,
        settings: AgentSettings,
        session_factory: Callable[[], AsyncSession],
        model_provider: RetrievalModelProvider,
        qdrant_store: QdrantKnowledgeStore,
        repository: KnowledgeRepository | None = None,
        query_rewriter: QueryRewriteProvider | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.model_provider = model_provider
        self.qdrant_store = qdrant_store
        self.repository = repository or KnowledgeRepository()
        self.query_rewriter = query_rewriter
        self._rewrite_cache: VersionedTTLCache[
            tuple[str, ...], tuple[str, str | None]
        ] = VersionedTTLCache(
            max_size=settings.rag_rewrite_cache_size,
            ttl_seconds=settings.rag_rewrite_cache_ttl_seconds,
        )
        self._embedding_cache: VersionedTTLCache[tuple[str, ...], list[float]] = VersionedTTLCache(
            max_size=settings.rag_embedding_cache_size,
            ttl_seconds=settings.rag_embedding_cache_ttl_seconds,
        )
        self._retrieval_cache: VersionedTTLCache[str, RetrievalResult] = VersionedTTLCache(
            max_size=settings.rag_retrieval_cache_size,
            ttl_seconds=settings.rag_retrieval_cache_ttl_seconds,
        )

    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
        rewrite_context: str | None = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        resolved_trace_id = trace_id or trace_id_context.get() or str(uuid4())
        original_query = normalize_query(query)
        if not original_query:
            raise ValueError("检索 Query 不能为空")
        timings: dict[str, int] = {}
        version_task = asyncio.create_task(self._knowledge_version(timings))
        rewrite_task = asyncio.create_task(
            self._rewrite(original_query, rewrite_context, timings)
        )
        knowledge_version, rewrite_result = await asyncio.gather(version_task, rewrite_task)
        rewritten_query, rewrite_error, rewrite_skipped, rewrite_cache_hit = rewrite_result

        embedding_started = time.perf_counter()
        embedding_identity = str(
            getattr(
                self.model_provider,
                "embedding_cache_identity",
                type(self.model_provider).__name__,
            )
        )
        embedding_key = (
            rewritten_query,
            embedding_identity,
            f"dense-v1|max_length={self.settings.rag_embedding_max_length}",
        )
        cached_vector = (
            self._embedding_cache.get(embedding_key)
            if self.settings.performance_optimizations_enabled
            else None
        )
        embedding_cache_hit = cached_vector is not None
        if cached_vector is None:
            query_vector = (
                await asyncio.to_thread(
                    self.model_provider.encode_dense,
                    [rewritten_query],
                    batch_size=self.settings.rag_embedding_batch_size,
                    max_length=self.settings.rag_embedding_max_length,
                )
            )[0]
            if self.settings.performance_optimizations_enabled:
                self._embedding_cache.put(embedding_key, list(query_vector))
        else:
            query_vector = list(cached_vector)
        timings["embedding_ms"] = self._elapsed_ms(embedding_started)

        retrieval_key = self._retrieval_cache_key(
            rewritten_query, query_vector, filters, knowledge_version
        )
        cached_result = (
            self._retrieval_cache.get(retrieval_key)
            if self.settings.performance_optimizations_enabled
            else None
        )
        if cached_result is not None:
            duration_ms = self._elapsed_ms(started)
            cached_trace = cached_result.trace.model_copy(
                deep=True,
                update={
                    "trace_id": resolved_trace_id,
                    "duration_ms": duration_ms,
                    "timings": RetrievalTimings(
                        knowledge_version_ms=timings.get("knowledge_version_ms", 0),
                        rewrite_ms=timings.get("rewrite_ms", 0),
                        embedding_ms=timings.get("embedding_ms", 0),
                        total_ms=duration_ms,
                    ),
                    "rewrite_skipped": rewrite_skipped,
                    "rewrite_cache_hit": rewrite_cache_hit,
                    "embedding_cache_hit": embedding_cache_hit,
                    "retrieval_cache_hit": True,
                    "knowledge_version": knowledge_version,
                },
            )
            return cached_result.model_copy(
                deep=True,
                update={
                    "original_query": original_query,
                    "rewritten_query": rewritten_query,
                    "rewrite_applied": rewritten_query != original_query,
                    "rewrite_error": rewrite_error,
                    "trace": cached_trace,
                },
            )

        filter_started = time.perf_counter()
        query_filter = self.qdrant_store.build_filter(filters)
        timings["filter_build_ms"] = self._elapsed_ms(filter_started)
        retrieval_started = time.perf_counter()

        async def measured_query(name: str, awaitable):
            query_started = time.perf_counter()
            result = await awaitable
            timings[f"{name}_query_ms"] = self._elapsed_ms(query_started)
            return result

        dense_points, sparse_points, fusion_points = await asyncio.gather(
            measured_query("dense", self.qdrant_store.query_dense(
                query_vector,
                query_filter=query_filter,
                limit=self.settings.rag_dense_top_k,
            )),
            measured_query("sparse", self.qdrant_store.query_sparse(
                rewritten_query,
                query_filter=query_filter,
                limit=self.settings.rag_sparse_top_k,
            )),
            measured_query("hybrid", self.qdrant_store.query_hybrid(
                query_vector,
                rewritten_query,
                query_filter=query_filter,
                dense_limit=self.settings.rag_dense_top_k,
                sparse_limit=self.settings.rag_sparse_top_k,
                fusion_limit=self.settings.rag_fusion_top_k,
                rrf_k=self.settings.rag_rrf_k,
            )),
        )
        timings["retrieval_wall_ms"] = self._elapsed_ms(retrieval_started)
        conversion_started = time.perf_counter()
        dense_candidates = self._candidates(dense_points)
        sparse_candidates = self._candidates(sparse_points)
        fusion_candidates = self._candidates(fusion_points)
        timings["candidate_conversion_ms"] = self._elapsed_ms(conversion_started)
        (
            evidences,
            context,
            rerank_trace,
            parent_trace,
            timings["rerank_ms"],
            timings["parent_db_ms"],
            timings["context_build_ms"],
        ) = await self._rerank_and_build_context(original_query, fusion_candidates)
        citations = [evidence.citation for evidence in evidences]
        answerable = bool(evidences)
        duration_ms = self._elapsed_ms(started)
        timings["total_ms"] = duration_ms
        trace = RetrievalTrace(
            trace_id=resolved_trace_id,
            original_query=original_query,
            rewritten_query=rewritten_query,
            rewrite_applied=rewritten_query != original_query,
            rewrite_error=rewrite_error,
            filters=filters,
            dense_candidates=dense_candidates,
            sparse_candidates=sparse_candidates,
            rrf_candidates=fusion_candidates,
            rerank_candidates=rerank_trace,
            final_evidence_ids=[item.payload.child_id for item in evidences],
            parent_lookups=parent_trace,
            citations=citations,
            duration_ms=duration_ms,
            timings=RetrievalTimings.model_validate(timings),
            rewrite_skipped=rewrite_skipped,
            rewrite_cache_hit=rewrite_cache_hit,
            embedding_cache_hit=embedding_cache_hit,
            retrieval_cache_hit=False,
            knowledge_version=knowledge_version,
        )
        result = RetrievalResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            rewrite_applied=rewritten_query != original_query,
            rewrite_error=rewrite_error,
            dense_candidates=dense_candidates,
            sparse_candidates=sparse_candidates,
            fusion_candidates=fusion_candidates,
            evidences=evidences,
            citations=citations,
            context=context,
            answerable=answerable,
            abstention_reason=None if answerable else "未检索到达到证据阈值的可见知识",
            trace=trace,
        )
        if self.settings.performance_optimizations_enabled:
            self._retrieval_cache.put(retrieval_key, result.model_copy(deep=True))
        return result

    async def _rewrite(
        self,
        query: str,
        context: str | None,
        timings: dict[str, int],
    ) -> tuple[str, str | None, bool, bool]:
        started = time.perf_counter()
        if self.query_rewriter is None:
            timings["rewrite_ms"] = self._elapsed_ms(started)
            return query, None, True, False
        if self.settings.performance_optimizations_enabled and can_skip_query_rewrite(query):
            timings["rewrite_ms"] = self._elapsed_ms(started)
            return query, None, True, False
        rewrite_identity = str(
            getattr(self.query_rewriter, "cache_identity", type(self.query_rewriter).__name__)
        )
        cache_key = (query, normalize_query(context or ""), rewrite_identity, QUERY_POLICY_VERSION)
        cached = (
            self._rewrite_cache.get(cache_key)
            if self.settings.performance_optimizations_enabled
            else None
        )
        if cached is not None:
            timings["rewrite_ms"] = self._elapsed_ms(started)
            return cached[0], cached[1], False, True
        try:
            rewritten = normalize_query(await self.query_rewriter.rewrite(query))
            if not rewritten:
                value = (query, "Query Rewrite 返回空文本，已使用原 Query")
            else:
                value = (rewritten, None)
        except Exception as exc:
            value = (query, f"Query Rewrite 失败，已使用原 Query：{exc}"[:1000])
        if self.settings.performance_optimizations_enabled:
            self._rewrite_cache.put(cache_key, value)
        timings["rewrite_ms"] = self._elapsed_ms(started)
        return value[0], value[1], False, False

    async def _knowledge_version(self, timings: dict[str, int]) -> str:
        started = time.perf_counter()
        method = getattr(self.repository, "get_ready_knowledge_version", None)
        if method is None:
            version = "unversioned-test-repository"
        else:
            async with self.session_factory() as session:
                version = str(await method(session))
        timings["knowledge_version_ms"] = self._elapsed_ms(started)
        return version

    def _retrieval_cache_key(
        self,
        query: str,
        query_vector: Sequence[float],
        filters: RetrievalFilters,
        knowledge_version: str,
    ) -> str:
        vector_bytes = struct.pack(f"<{len(query_vector)}f", *query_vector)
        vector_digest = hashlib.sha256(vector_bytes).hexdigest()
        reranker_identity = str(
            getattr(
                self.model_provider,
                "reranker_cache_identity",
                type(self.model_provider).__name__,
            )
        )
        payload = {
            "pipeline": "hybrid-rrf-rerank-parent-v2",
            "query": query,
            "embedding": vector_digest,
            "filters": filters.model_dump(mode="json"),
            "knowledge_version": knowledge_version,
            "collection": self.settings.qdrant_collection,
            "dense_top_k": self.settings.rag_dense_top_k,
            "sparse_top_k": self.settings.rag_sparse_top_k,
            "fusion_top_k": self.settings.rag_fusion_top_k,
            "rerank_top_k": self.settings.rag_rerank_top_k,
            "rerank_min_score": self.settings.rag_rerank_min_score,
            "reranker": reranker_identity,
            "context_max_chars": self.settings.rag_context_max_chars,
            "parent_max_chars": self.settings.rag_parent_max_chars,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))

    @staticmethod
    def _candidates(points: Sequence[models.ScoredPoint]) -> list[RetrievalCandidate]:
        candidates: list[RetrievalCandidate] = []
        for point in points:
            if point.payload is None:
                raise ValueError(f"Qdrant Child 缺少 Payload：{point.id}")
            candidates.append(
                RetrievalCandidate(
                    payload=ChildChunkPayload.model_validate(point.payload),
                    score=float(point.score),
                )
            )
        return candidates

    async def _rerank_and_build_context(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> tuple[
        list[RetrievedEvidence],
        str,
        list[RerankTraceItem],
        list[ParentLookupTrace],
        int,
        int,
        int,
    ]:
        if not candidates:
            return [], "", [], [], 0, 0, 0
        rerank_documents = [self._rerank_text(candidate.payload) for candidate in candidates]
        rerank_started = time.perf_counter()
        rerank_scores = await asyncio.to_thread(
            self.model_provider.rerank,
            query,
            rerank_documents,
            normalize=True,
            batch_size=self.settings.rag_reranker_batch_size,
        )
        rerank_ms = self._elapsed_ms(rerank_started)
        if len(rerank_scores) != len(candidates):
            raise ValueError("Reranker 返回分数数量与融合候选不一致")
        all_ranked = sorted(
            zip(candidates, rerank_scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        rerank_trace = [
            RerankTraceItem(
                child_id=candidate.payload.child_id,
                fusion_score=candidate.score,
                rerank_score=float(score),
            )
            for candidate, score in all_ranked
        ]
        ranked = [item for item in all_ranked if item[1] >= self.settings.rag_rerank_min_score][
            : self.settings.rag_rerank_top_k
        ]
        if not ranked:
            return [], "", rerank_trace, [], rerank_ms, 0, 0
        parent_ids = list(dict.fromkeys(item.payload.parent_id for item, _score in ranked))
        parent_started = time.perf_counter()
        async with self.session_factory() as session:
            parents = await self.repository.get_ready_parents_by_ids(session, parent_ids)
        parent_db_ms = self._elapsed_ms(parent_started)
        parent_map = {parent.parent_id: parent for parent in parents}
        context_started = time.perf_counter()
        evidences, context, parent_trace = self._build_context(query, ranked, parent_map)
        context_build_ms = self._elapsed_ms(context_started)
        return (
            evidences,
            context,
            rerank_trace,
            parent_trace,
            rerank_ms,
            parent_db_ms,
            context_build_ms,
        )

    def _build_context(
        self,
        query: str,
        ranked: Sequence[tuple[RetrievalCandidate, float]],
        parent_map: dict[str, KnowledgeParent],
    ) -> tuple[list[RetrievedEvidence], str, list[ParentLookupTrace]]:
        evidences: list[RetrievedEvidence] = []
        context_parts: list[str] = []
        parent_trace: list[ParentLookupTrace] = []
        used_parent_ids: set[str] = set()
        remaining = self.settings.rag_context_max_chars
        for candidate, rerank_score in ranked:
            payload = candidate.payload
            parent = parent_map.get(payload.parent_id)
            expand = self._should_expand_parent(query, payload, parent)
            if expand and payload.parent_id in used_parent_ids:
                continue
            content = parent.content if expand and parent is not None else payload.content
            citation = self._citation(payload, len(evidences) + 1)
            header = (
                f"[{citation.citation_id}] {payload.document_id} v{payload.version} | "
                f"{' > '.join(payload.section_path)}\n"
            )
            entry = f"{header}{content}"
            truncated = False
            if len(entry) > remaining and expand:
                expand = False
                content = payload.content
                entry = f"{header}{content}"
            if len(entry) > remaining:
                if evidences or remaining <= len(header):
                    continue
                content = content[: remaining - len(header)].rstrip()
                entry = f"{header}{content}"
                truncated = True
            evidences.append(
                RetrievedEvidence(
                    payload=payload,
                    fusion_score=candidate.score,
                    rerank_score=float(rerank_score),
                    context_content=content,
                    citation=citation,
                    parent_expanded=expand,
                    context_truncated=truncated,
                )
            )
            context_parts.append(entry)
            remaining -= len(entry) + 2
            if expand:
                used_parent_ids.add(payload.parent_id)
            parent_trace.append(
                ParentLookupTrace(
                    parent_id=payload.parent_id,
                    child_id=payload.child_id,
                    found_ready=parent is not None,
                    expanded=expand,
                )
            )
            if remaining <= 0:
                break
        return evidences, "\n\n".join(context_parts), parent_trace

    @staticmethod
    def _citation(payload: ChildChunkPayload, ordinal: int) -> KnowledgeCitation:
        return KnowledgeCitation(
            citation_id=f"K{ordinal}",
            child_id=payload.child_id,
            parent_id=payload.parent_id,
            document_id=payload.document_id,
            document_title=payload.title,
            version=payload.version,
            section_path=payload.section_path,
            source_path=payload.source_path,
            source_start_line=payload.source_start_line,
            source_end_line=payload.source_end_line,
        )

    def _should_expand_parent(
        self,
        query: str,
        payload: ChildChunkPayload,
        parent: KnowledgeParent | None,
    ) -> bool:
        if parent is None or payload.chunk_type not in _PARENT_EXPAND_TYPES:
            return False
        if parent.content.strip() == payload.content.strip():
            return False
        if len(parent.content) > self.settings.rag_parent_max_chars:
            return False
        return payload.chunk_type == "section" or any(
            signal in query for signal in _PARENT_QUERY_SIGNALS
        )

    @staticmethod
    def _rerank_text(payload: ChildChunkPayload) -> str:
        return "\n".join(
            [
                f"文档标题：{payload.title}",
                f"章节路径：{' > '.join(payload.section_path)}",
                f"主题：{payload.topic}",
                payload.content,
            ]
        )
