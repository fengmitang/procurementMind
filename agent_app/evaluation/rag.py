from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_app.graph.router import FirstVersionRouter
from agent_app.graph.schemas import RouteType
from agent_app.rag.schemas import RetrievalFilters, RetrievalResult


class RetrievalStrategy(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"
    HYBRID_RERANKER = "hybrid_reranker"


class RAGEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)
    expected_route: RouteType
    expected_retrieval: bool
    relevant_parent_ids: list[str] = Field(default_factory=list)


class StrategyCaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_at_k: float = Field(ge=0, le=1)
    reciprocal_rank: float = Field(ge=0, le=1)
    retrieved_parent_ids: list[str]


class RAGCaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    expected_route: RouteType
    actual_route: RouteType
    route_correct: bool
    retrieval_executed: bool
    relevant_parent_ids: list[str] = Field(default_factory=list)
    answerable: bool | None = None
    citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    strategies: dict[RetrievalStrategy, StrategyCaseMetrics] = Field(default_factory=dict)
    trace_id: str | None = None
    trace: dict | None = None


class RetrievalStrategyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluated_cases: int = Field(ge=0)
    recall_at_k: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)


class RAGEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str
    generated_at: datetime
    evaluation_k: int = Field(ge=1)
    total_cases: int = Field(ge=0)
    route_accuracy: float = Field(ge=0, le=1)
    citation_accuracy: float = Field(ge=0, le=1)
    negative_accuracy: float = Field(ge=0, le=1)
    strategies: dict[RetrievalStrategy, RetrievalStrategyMetrics]
    cases: list[RAGCaseEvaluation]


class RAGStrategyBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_recall_at_k: float = Field(ge=0, le=1)
    minimum_mrr: float = Field(ge=0, le=1)


class RAGEvaluationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_version: str
    expected_total_cases: int = Field(ge=1)
    evaluation_k: int = Field(ge=1)
    minimum_route_accuracy: float = Field(ge=0, le=1)
    minimum_citation_accuracy: float = Field(ge=0, le=1)
    minimum_negative_accuracy: float = Field(ge=0, le=1)
    strategies: dict[RetrievalStrategy, RAGStrategyBaseline]


class RAGBaselineComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_version: str
    passed: bool
    mismatches: list[str] = Field(default_factory=list)


class RAGEvaluationRetriever(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult: ...


def load_rag_evaluation_cases(path: Path) -> list[RAGEvaluationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"RAG 评测文件必须是 JSON 数组：{path}")
    cases = [RAGEvaluationCase.model_validate(item) for item in data]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("RAG 评测 case_id 必须唯一")
    return cases


def compare_rag_with_baseline(
    report: RAGEvaluationReport,
    baseline: RAGEvaluationBaseline,
) -> RAGBaselineComparison:
    mismatches: list[str] = []
    exact_values = {
        "total_cases": (baseline.expected_total_cases, report.total_cases),
        "evaluation_k": (baseline.evaluation_k, report.evaluation_k),
    }
    for name, (expected, actual) in exact_values.items():
        if actual != expected:
            mismatches.append(f"{name}: expected={expected}, actual={actual}")
    minimum_values = {
        "route_accuracy": (baseline.minimum_route_accuracy, report.route_accuracy),
        "citation_accuracy": (
            baseline.minimum_citation_accuracy,
            report.citation_accuracy,
        ),
        "negative_accuracy": (baseline.minimum_negative_accuracy, report.negative_accuracy),
    }
    for name, (minimum, actual) in minimum_values.items():
        if actual < minimum:
            mismatches.append(f"{name}: minimum={minimum}, actual={actual}")
    for strategy, expectation in baseline.strategies.items():
        actual = report.strategies.get(strategy)
        if actual is None:
            mismatches.append(f"strategies.{strategy}: missing")
            continue
        if actual.recall_at_k < expectation.minimum_recall_at_k:
            mismatches.append(
                f"strategies.{strategy}.recall_at_k: "
                f"minimum={expectation.minimum_recall_at_k}, actual={actual.recall_at_k}"
            )
        if actual.mrr < expectation.minimum_mrr:
            mismatches.append(
                f"strategies.{strategy}.mrr: minimum={expectation.minimum_mrr}, actual={actual.mrr}"
            )
    return RAGBaselineComparison(
        baseline_version=baseline.baseline_version,
        passed=not mismatches,
        mismatches=mismatches,
    )


class RAGEvaluator:
    def __init__(self, *, evaluation_k: int = 5) -> None:
        if evaluation_k < 1:
            raise ValueError("evaluation_k 必须大于 0")
        self.evaluation_k = evaluation_k
        self.router = FirstVersionRouter()

    async def run(
        self,
        cases: list[RAGEvaluationCase],
        retriever: RAGEvaluationRetriever,
    ) -> RAGEvaluationReport:
        results: list[RAGCaseEvaluation] = []
        for case in cases:
            actual_route = self.router.classify(case.query)
            if not case.expected_retrieval:
                results.append(
                    RAGCaseEvaluation(
                        case_id=case.case_id,
                        category=case.category,
                        expected_route=case.expected_route,
                        actual_route=actual_route,
                        route_correct=actual_route == case.expected_route,
                        retrieval_executed=False,
                        relevant_parent_ids=case.relevant_parent_ids,
                    )
                )
                continue
            retrieval = await retriever.retrieve(
                case.query,
                filters=RetrievalFilters(allowed_roles=case.roles),
                trace_id=f"rag-eval-{case.case_id}",
            )
            rankings = self._rankings(retrieval)
            strategy_metrics = {
                strategy: self._case_metrics(ranking, case.relevant_parent_ids)
                for strategy, ranking in rankings.items()
            }
            results.append(
                RAGCaseEvaluation(
                    case_id=case.case_id,
                    category=case.category,
                    expected_route=case.expected_route,
                    actual_route=actual_route,
                    route_correct=actual_route == case.expected_route,
                    retrieval_executed=True,
                    relevant_parent_ids=case.relevant_parent_ids,
                    answerable=retrieval.answerable,
                    citation_accuracy=self._citation_accuracy(case, retrieval),
                    strategies=strategy_metrics,
                    trace_id=retrieval.trace.trace_id,
                    trace=retrieval.trace.model_dump(mode="json"),
                )
            )
        return self._report(results)

    def _rankings(self, result: RetrievalResult) -> dict[RetrievalStrategy, list[str]]:
        child_to_parent = {
            candidate.payload.child_id: candidate.payload.parent_id
            for candidate in result.fusion_candidates
        }
        return {
            RetrievalStrategy.DENSE: [
                candidate.payload.parent_id for candidate in result.dense_candidates
            ],
            RetrievalStrategy.SPARSE: [
                candidate.payload.parent_id for candidate in result.sparse_candidates
            ],
            RetrievalStrategy.HYBRID: [
                candidate.payload.parent_id for candidate in result.fusion_candidates
            ],
            RetrievalStrategy.HYBRID_RERANKER: [
                child_to_parent[item.child_id]
                for item in result.trace.rerank_candidates[: self.evaluation_k]
                if item.child_id in child_to_parent
            ],
        }

    def _case_metrics(
        self,
        ranking: list[str],
        relevant_parent_ids: list[str],
    ) -> StrategyCaseMetrics:
        relevant = set(relevant_parent_ids)
        top_k = ranking[: self.evaluation_k]
        if not relevant:
            return StrategyCaseMetrics(
                recall_at_k=1.0 if not top_k else 0.0,
                reciprocal_rank=1.0 if not top_k else 0.0,
                retrieved_parent_ids=top_k,
            )
        recall = len(relevant.intersection(top_k)) / len(relevant)
        first_rank = next(
            (index for index, parent_id in enumerate(top_k, start=1) if parent_id in relevant),
            None,
        )
        return StrategyCaseMetrics(
            recall_at_k=recall,
            reciprocal_rank=1 / first_rank if first_rank is not None else 0.0,
            retrieved_parent_ids=top_k,
        )

    @staticmethod
    def _citation_accuracy(case: RAGEvaluationCase, result: RetrievalResult) -> float:
        if not result.citations:
            return 1.0 if not case.relevant_parent_ids and not result.answerable else 0.0
        evidence_by_citation = {item.citation.citation_id: item for item in result.evidences}
        accurate = 0
        for citation in result.citations:
            evidence = evidence_by_citation.get(citation.citation_id)
            if evidence is None:
                continue
            payload = evidence.payload
            visible = bool(set(payload.allowed_roles).intersection(case.roles))
            exact_source = (
                citation.child_id == payload.child_id
                and citation.parent_id == payload.parent_id
                and citation.document_id == payload.document_id
                and citation.version == payload.version
                and citation.section_path == payload.section_path
                and citation.source_path == payload.source_path
                and citation.source_start_line == payload.source_start_line
                and citation.source_end_line == payload.source_end_line
            )
            if visible and exact_source and f"[{citation.citation_id}]" in result.context:
                accurate += 1
        return accurate / len(result.citations)

    def _report(self, results: list[RAGCaseEvaluation]) -> RAGEvaluationReport:
        positive_results = [
            result for result in results if result.retrieval_executed and result.relevant_parent_ids
        ]
        strategies: dict[RetrievalStrategy, RetrievalStrategyMetrics] = {}
        for strategy in RetrievalStrategy:
            metrics = [result.strategies[strategy] for result in positive_results]
            strategies[strategy] = RetrievalStrategyMetrics(
                evaluated_cases=len(metrics),
                recall_at_k=sum(item.recall_at_k for item in metrics) / len(metrics)
                if metrics
                else 0,
                mrr=sum(item.reciprocal_rank for item in metrics) / len(metrics) if metrics else 0,
            )
        citation_scores = [
            result.citation_accuracy for result in results if result.citation_accuracy is not None
        ]
        negative_results = [
            result
            for result in results
            if result.retrieval_executed and not result.relevant_parent_ids
        ]
        return RAGEvaluationReport(
            report_version="rag-v0.1",
            generated_at=datetime.now(UTC),
            evaluation_k=self.evaluation_k,
            total_cases=len(results),
            route_accuracy=sum(result.route_correct for result in results) / len(results)
            if results
            else 0,
            citation_accuracy=sum(citation_scores) / len(citation_scores) if citation_scores else 0,
            negative_accuracy=sum(result.answerable is False for result in negative_results)
            / len(negative_results)
            if negative_results
            else 0,
            strategies=strategies,
            cases=results,
        )
