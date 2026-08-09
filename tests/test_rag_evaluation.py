from pathlib import Path
from uuid import uuid4

import pytest

from agent_app.evaluation.rag import (
    RAGEvaluationBaseline,
    RAGEvaluationCase,
    RAGEvaluator,
    RetrievalStrategy,
    compare_rag_with_baseline,
    load_rag_evaluation_cases,
)
from agent_app.graph.router import FirstVersionRouter
from agent_app.rag.schemas import (
    ChildChunkPayload,
    KnowledgeCitation,
    RerankTraceItem,
    RetrievalCandidate,
    RetrievalResult,
    RetrievalTrace,
    RetrievedEvidence,
)

ROOT = Path(__file__).resolve().parents[1]


def child(parent_id: str, *, child_id: str | None = None) -> ChildChunkPayload:
    return ChildChunkPayload(
        child_id=child_id or str(uuid4()),
        parent_id=parent_id,
        document_id="CGXT-ZY-01",
        title="采购规则",
        section_path=["申请", "提交"],
        topic="提交规则",
        chunk_type="rule",
        version="1.0",
        status="ACTIVE",
        content="提交前应补齐必填字段。",
        source_path="knowledge/source/01.md",
        source_start_line=10,
        source_end_line=12,
        allowed_roles=["APPLICANT"],
    )


def result(*, positive: bool) -> RetrievalResult:
    relevant = child("parent-relevant")
    other = child("parent-other")
    dense = [RetrievalCandidate(payload=relevant, score=0.9)] if positive else []
    sparse = (
        [
            RetrievalCandidate(payload=other, score=2.0),
            RetrievalCandidate(payload=relevant, score=1.5),
        ]
        if positive
        else []
    )
    fusion = (
        [
            RetrievalCandidate(payload=other, score=0.03),
            RetrievalCandidate(payload=relevant, score=0.02),
        ]
        if positive
        else []
    )
    citation = KnowledgeCitation(
        citation_id="K1",
        child_id=relevant.child_id,
        parent_id=relevant.parent_id,
        document_id=relevant.document_id,
        document_title=relevant.title,
        version=relevant.version,
        section_path=relevant.section_path,
        source_path=relevant.source_path,
        source_start_line=relevant.source_start_line,
        source_end_line=relevant.source_end_line,
    )
    evidences = (
        [
            RetrievedEvidence(
                payload=relevant,
                fusion_score=0.02,
                rerank_score=0.99,
                context_content=relevant.content,
                citation=citation,
            )
        ]
        if positive
        else []
    )
    reranked = (
        [
            RerankTraceItem(
                child_id=relevant.child_id,
                fusion_score=0.02,
                rerank_score=0.99,
            ),
            RerankTraceItem(
                child_id=other.child_id,
                fusion_score=0.03,
                rerank_score=0.2,
            ),
        ]
        if positive
        else []
    )
    trace = RetrievalTrace(
        trace_id="rag-eval-test",
        original_query="采购流程规定",
        rewritten_query="采购流程规定",
        rewrite_applied=False,
        filters={"allowed_roles": ["APPLICANT"]},
        dense_candidates=dense,
        sparse_candidates=sparse,
        rrf_candidates=fusion,
        rerank_candidates=reranked,
        final_evidence_ids=[relevant.child_id] if positive else [],
        parent_lookups=[],
        citations=[citation] if positive else [],
        duration_ms=1,
    )
    return RetrievalResult(
        original_query="采购流程规定",
        rewritten_query="采购流程规定",
        dense_candidates=dense,
        sparse_candidates=sparse,
        fusion_candidates=fusion,
        evidences=evidences,
        citations=[citation] if positive else [],
        context=f"[K1] {relevant.content}" if positive else "",
        answerable=positive,
        abstention_reason=None if positive else "无证据",
        trace=trace,
    )


class FakeRetriever:
    async def retrieve(self, query: str, **_kwargs) -> RetrievalResult:
        return result(positive="年假" not in query)


@pytest.mark.asyncio
async def test_rag_evaluator_reports_four_strategies_routes_citations_and_negative() -> None:
    cases = [
        RAGEvaluationCase(
            case_id="positive",
            category="direct",
            query="采购流程规定",
            roles=["APPLICANT"],
            expected_route="KNOWLEDGE",
            expected_retrieval=True,
            relevant_parent_ids=["parent-relevant"],
        ),
        RAGEvaluationCase(
            case_id="negative",
            category="negative",
            query="公司的年假怎么申请",
            roles=["APPLICANT"],
            expected_route="KNOWLEDGE",
            expected_retrieval=True,
            relevant_parent_ids=[],
        ),
        RAGEvaluationCase(
            case_id="realtime",
            category="realtime",
            query="采购申请 91007 当前状态",
            roles=["APPLICANT"],
            expected_route="REALTIME_BUSINESS",
            expected_retrieval=False,
        ),
    ]

    report = await RAGEvaluator(evaluation_k=5).run(cases, FakeRetriever())

    assert report.route_accuracy == 1
    assert report.citation_accuracy == 1
    assert report.negative_accuracy == 1
    assert report.strategies[RetrievalStrategy.DENSE].recall_at_k == 1
    assert report.strategies[RetrievalStrategy.DENSE].mrr == 1
    assert report.strategies[RetrievalStrategy.SPARSE].mrr == 0.5
    assert report.strategies[RetrievalStrategy.HYBRID].mrr == 0.5
    assert report.strategies[RetrievalStrategy.HYBRID_RERANKER].mrr == 1
    assert report.cases[0].trace is not None
    assert report.cases[2].retrieval_executed is False

    baseline = RAGEvaluationBaseline(
        baseline_version="test",
        expected_total_cases=3,
        evaluation_k=5,
        minimum_route_accuracy=1,
        minimum_citation_accuracy=1,
        minimum_negative_accuracy=1,
        strategies={
            "dense": {"minimum_recall_at_k": 1, "minimum_mrr": 1},
            "sparse": {"minimum_recall_at_k": 1, "minimum_mrr": 0.5},
            "hybrid": {"minimum_recall_at_k": 1, "minimum_mrr": 0.5},
            "hybrid_reranker": {"minimum_recall_at_k": 1, "minimum_mrr": 1},
        },
    )
    assert compare_rag_with_baseline(report, baseline).passed is True

    baseline.strategies[RetrievalStrategy.HYBRID_RERANKER].minimum_mrr = 1.0
    report.strategies[RetrievalStrategy.HYBRID_RERANKER].mrr = 0.9
    comparison = compare_rag_with_baseline(report, baseline)
    assert comparison.passed is False
    assert "hybrid_reranker.mrr" in comparison.mismatches[0]


def test_fixed_rag_dataset_has_required_categories_unique_ids_and_expected_routes() -> None:
    cases = load_rag_evaluation_cases(ROOT / "tests" / "fixtures" / "rag_evaluation_v0.1.json")
    categories = {case.category for case in cases}

    assert len(cases) >= 9
    assert {
        "direct",
        "colloquial",
        "synonym",
        "multi-clause",
        "faq",
        "permission",
        "negative",
        "realtime",
        "hybrid",
        "rag-tool-mixed",
    }.issubset(categories)
    router = FirstVersionRouter()
    assert all(router.classify(case.query) == case.expected_route for case in cases)
