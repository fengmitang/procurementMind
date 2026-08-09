from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qdrant_client import models

from agent_app.core.config import AgentSettings
from agent_app.rag.qdrant import QdrantKnowledgeStore
from agent_app.rag.retriever import KnowledgeRetriever
from agent_app.rag.schemas import ChildChunkPayload, RetrievalFilters


def settings(**updates: object) -> AgentSettings:
    values = {
        "identity_gateway_secret": "retriever-test-secret",
        "rag_dense_top_k": 3,
        "rag_sparse_top_k": 3,
        "rag_fusion_top_k": 3,
        "rag_rerank_top_k": 2,
        "rag_context_max_chars": 1000,
        "rag_parent_max_chars": 800,
    }
    values.update(updates)
    return AgentSettings(_env_file=None, **values)


def payload(
    child_id: str,
    parent_id: str,
    *,
    chunk_type: str = "rule",
    content: str = "提交采购申请前应补齐必填字段。",
) -> dict:
    return ChildChunkPayload(
        child_id=child_id,
        parent_id=parent_id,
        document_id="CGXT-ZY-01",
        title="数据中心设备采购业务管理与流程指引",
        section_path=["申请阶段", "提交要求"],
        topic="提交要求",
        chunk_type=chunk_type,
        version="1.0",
        status="ACTIVE",
        content=content,
        source_path="knowledge/source/01.md",
        source_start_line=20,
        source_end_line=25,
        allowed_roles=["APPLICANT"],
    ).model_dump(mode="json")


def point(point_payload: dict, score: float) -> models.ScoredPoint:
    return models.ScoredPoint(
        id=point_payload["child_id"],
        version=1,
        score=score,
        payload=point_payload,
    )


class FakeModels:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.embedded: list[str] = []
        self.reranked: list[str] = []

    def encode_dense(self, texts: list[str], *, batch_size: int, max_length: int):
        assert batch_size == 4
        assert max_length == 512
        self.embedded.extend(texts)
        return [[1.0] + [0.0] * 1023 for _ in texts]

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool,
        batch_size: int,
    ) -> list[float]:
        assert query
        assert normalize is True
        assert batch_size == 4
        self.reranked.extend(documents)
        return self.scores


class FakeStore:
    build_filter = staticmethod(QdrantKnowledgeStore.build_filter)

    def __init__(self, points: list[models.ScoredPoint]) -> None:
        self.points = points
        self.calls: list[tuple[str, object]] = []

    async def query_dense(self, query_vector, *, query_filter, limit):
        self.calls.append(("dense", (query_vector, query_filter, limit)))
        return self.points

    async def query_sparse(self, query_text, *, query_filter, limit):
        self.calls.append(("sparse", (query_text, query_filter, limit)))
        return list(reversed(self.points))

    async def query_hybrid(self, query_vector, query_text, **kwargs):
        self.calls.append(("hybrid", (query_vector, query_text, kwargs)))
        return self.points


class FakeRepository:
    def __init__(self, parents: list[object]) -> None:
        self.parents = parents
        self.requested: list[str] = []

    async def get_ready_parents_by_ids(self, _session, parent_ids):
        self.requested.extend(parent_ids)
        return [parent for parent in self.parents if parent.parent_id in parent_ids]


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class Rewriter:
    def __init__(self, result: str | Exception) -> None:
        self.result = result

    async def rewrite(self, _query: str) -> str:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_hybrid_retrieval_reranks_and_selectively_expands_parent() -> None:
    first_parent = str(uuid4())
    second_parent = str(uuid4())
    first = payload(str(uuid4()), first_parent)
    second = payload(
        str(uuid4()), second_parent, chunk_type="faq", content="提交后可在申请列表查看。"
    )
    points = [point(first, 0.7), point(second, 0.9)]
    parent = SimpleNamespace(
        parent_id=first_parent,
        content="申请提交完整流程：填写设备信息，保存草稿，补齐必填字段后提交。",
    )
    model_provider = FakeModels([0.95, 0.7])
    store = FakeStore(points)
    repository = FakeRepository([parent])
    retriever = KnowledgeRetriever(
        settings=settings(),
        session_factory=FakeSession,
        model_provider=model_provider,
        qdrant_store=store,
        repository=repository,
        query_rewriter=Rewriter("采购申请完整提交流程"),
    )

    result = await retriever.retrieve(
        "采购申请如何提交？",
        filters=RetrievalFilters(allowed_roles=["APPLICANT"]),
    )

    assert result.rewrite_applied is True
    assert result.rewritten_query == "采购申请完整提交流程"
    assert [name for name, _call in store.calls] == ["dense", "sparse", "hybrid"]
    assert result.evidences[0].payload.child_id == first["child_id"]
    assert result.evidences[0].parent_expanded is True
    assert "申请提交完整流程" in result.evidences[0].context_content
    assert result.evidences[1].parent_expanded is False
    assert "文档标题：" in model_provider.reranked[0]
    assert result.answerable is True
    assert result.citations[0].citation_id == "K1"
    assert result.citations[0].source_start_line == 20
    assert result.context.startswith("[K1]")
    assert result.trace.trace_id
    assert result.trace.final_evidence_ids == [
        evidence.payload.child_id for evidence in result.evidences
    ]
    assert len(result.trace.rerank_candidates) == 2
    assert result.trace.parent_lookups[0].expanded is True


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_to_original_and_empty_results_skip_reranker() -> None:
    model_provider = FakeModels([])
    retriever = KnowledgeRetriever(
        settings=settings(),
        session_factory=FakeSession,
        model_provider=model_provider,
        qdrant_store=FakeStore([]),
        repository=FakeRepository([]),
        query_rewriter=Rewriter(RuntimeError("provider unavailable")),
    )

    result = await retriever.retrieve(
        "  黑名单 如何 核实  ",
        filters=RetrievalFilters(allowed_roles=["PURCHASER"]),
    )

    assert result.rewritten_query == "黑名单 如何 核实"
    assert result.rewrite_applied is False
    assert "provider unavailable" in result.rewrite_error
    assert result.evidences == []
    assert result.context == ""
    assert model_provider.reranked == []
    assert result.answerable is False
    assert result.abstention_reason
    assert result.trace.rewrite_error == result.rewrite_error


@pytest.mark.asyncio
async def test_context_budget_falls_back_from_parent_and_marks_child_truncation() -> None:
    parent_id = str(uuid4())
    child = payload(str(uuid4()), parent_id, content="子片段" * 400)
    retriever = KnowledgeRetriever(
        settings=settings(rag_context_max_chars=500, rag_parent_max_chars=400),
        session_factory=FakeSession,
        model_provider=FakeModels([0.9]),
        qdrant_store=FakeStore([point(child, 0.8)]),
        repository=FakeRepository(
            [SimpleNamespace(parent_id=parent_id, content="完整父内容" * 200)]
        ),
    )

    result = await retriever.retrieve(
        "完整流程是什么",
        filters=RetrievalFilters(allowed_roles=["APPLICANT"]),
    )

    assert len(result.context) <= 500
    assert result.evidences[0].parent_expanded is False
    assert result.evidences[0].context_truncated is True


def test_retrieval_configuration_rejects_invalid_top_k_and_context_budget() -> None:
    with pytest.raises(ValidationError, match="RAG_RERANK_TOP_K"):
        settings(rag_fusion_top_k=2, rag_rerank_top_k=3)
    with pytest.raises(ValidationError, match="RAG_PARENT_MAX_CHARS"):
        settings(rag_context_max_chars=500, rag_parent_max_chars=600)


def test_retrieval_filter_requires_role_and_active_status() -> None:
    with pytest.raises(ValidationError, match="allowed_roles"):
        RetrievalFilters()
    with pytest.raises(ValidationError, match="status"):
        RetrievalFilters(allowed_roles=["ADMIN"], status="RETIRED")


@pytest.mark.asyncio
async def test_low_reranker_scores_produce_no_citation_or_context() -> None:
    child = payload(str(uuid4()), str(uuid4()))
    retriever = KnowledgeRetriever(
        settings=settings(rag_rerank_min_score=0.8),
        session_factory=FakeSession,
        model_provider=FakeModels([0.79]),
        qdrant_store=FakeStore([point(child, 0.8)]),
        repository=FakeRepository([]),
    )

    result = await retriever.retrieve(
        "与采购制度无关的问题",
        filters=RetrievalFilters(allowed_roles=["APPLICANT"]),
        trace_id="trace-low-score",
    )

    assert result.answerable is False
    assert result.citations == []
    assert result.context == ""
    assert result.trace.trace_id == "trace-low-score"
    assert len(result.trace.rerank_candidates) == 1
