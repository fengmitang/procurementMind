from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import uuid4

from qdrant_client import models
from sqlalchemy.ext.asyncio import AsyncSession

from agent_app.core.config import AgentSettings
from agent_app.core.request_context import trace_id_context
from agent_app.rag.qdrant import QdrantKnowledgeStore
from agent_app.rag.schemas import (
    ChildChunkPayload,
    KnowledgeCitation,
    ParentLookupTrace,
    RerankTraceItem,
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalResult,
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

    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        resolved_trace_id = trace_id or trace_id_context.get() or str(uuid4())
        original_query = " ".join(query.split())
        if not original_query:
            raise ValueError("检索 Query 不能为空")
        rewritten_query, rewrite_error = await self._rewrite(original_query)
        query_vector = (
            await asyncio.to_thread(
                self.model_provider.encode_dense,
                [rewritten_query],
                batch_size=self.settings.rag_embedding_batch_size,
                max_length=self.settings.rag_embedding_max_length,
            )
        )[0]
        query_filter = self.qdrant_store.build_filter(filters)
        dense_points, sparse_points, fusion_points = await asyncio.gather(
            self.qdrant_store.query_dense(
                query_vector,
                query_filter=query_filter,
                limit=self.settings.rag_dense_top_k,
            ),
            self.qdrant_store.query_sparse(
                rewritten_query,
                query_filter=query_filter,
                limit=self.settings.rag_sparse_top_k,
            ),
            self.qdrant_store.query_hybrid(
                query_vector,
                rewritten_query,
                query_filter=query_filter,
                dense_limit=self.settings.rag_dense_top_k,
                sparse_limit=self.settings.rag_sparse_top_k,
                fusion_limit=self.settings.rag_fusion_top_k,
                rrf_k=self.settings.rag_rrf_k,
            ),
        )
        dense_candidates = self._candidates(dense_points)
        sparse_candidates = self._candidates(sparse_points)
        fusion_candidates = self._candidates(fusion_points)
        evidences, context, rerank_trace, parent_trace = await self._rerank_and_build_context(
            original_query,
            fusion_candidates,
        )
        citations = [evidence.citation for evidence in evidences]
        answerable = bool(evidences)
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
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )
        return RetrievalResult(
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

    async def _rewrite(self, query: str) -> tuple[str, str | None]:
        if self.query_rewriter is None:
            return query, None
        try:
            rewritten = " ".join((await self.query_rewriter.rewrite(query)).split())
            if not rewritten:
                return query, "Query Rewrite 返回空文本，已使用原 Query"
            return rewritten, None
        except Exception as exc:
            return query, f"Query Rewrite 失败，已使用原 Query：{exc}"[:1000]

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
    ]:
        if not candidates:
            return [], "", [], []
        rerank_documents = [self._rerank_text(candidate.payload) for candidate in candidates]
        rerank_scores = await asyncio.to_thread(
            self.model_provider.rerank,
            query,
            rerank_documents,
            normalize=True,
            batch_size=self.settings.rag_reranker_batch_size,
        )
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
            return [], "", rerank_trace, []
        parent_ids = list(dict.fromkeys(item.payload.parent_id for item, _score in ranked))
        async with self.session_factory() as session:
            parents = await self.repository.get_ready_parents_by_ids(session, parent_ids)
        parent_map = {parent.parent_id: parent for parent in parents}
        evidences, context, parent_trace = self._build_context(query, ranked, parent_map)
        return evidences, context, rerank_trace, parent_trace

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
