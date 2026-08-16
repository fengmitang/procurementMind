from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from agent_app.device_terms.service import DeviceTermSearchService
from agent_app.device_terms.text import normalize_device_name
from app.schemas.procurement import DeviceType


class DeviceTermEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    query: str
    target: str
    device_profession: DeviceType


class DeviceTermCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    like_hit: bool
    semantic_rank: int | None
    semantic_top1_hit: bool
    semantic_top3_hit: bool
    semantic_top5_hit: bool
    candidates: list[str]
    error_code: str | None = None
    embedding_latency_ms: int = Field(ge=0)
    qdrant_latency_ms: int = Field(ge=0)
    total_latency_ms: int = Field(ge=0)


class DeviceTermEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int
    like_hit_rate: float = Field(ge=0, le=1)
    semantic_top1_hit_rate: float = Field(ge=0, le=1)
    semantic_top3_hit_rate: float = Field(ge=0, le=1)
    semantic_top5_hit_rate: float = Field(ge=0, le=1)
    average_embedding_latency_ms: float = Field(ge=0)
    average_qdrant_latency_ms: float = Field(ge=0)
    average_total_latency_ms: float = Field(ge=0)
    p95_total_latency_ms: int = Field(ge=0)
    results: list[DeviceTermCaseResult]


class DeviceTermEvaluator:
    def __init__(self, search: DeviceTermSearchService) -> None:
        self.search = search

    async def run(
        self,
        cases: list[DeviceTermEvaluationCase],
    ) -> DeviceTermEvaluationReport:
        results = []
        for case in cases:
            lookup = await self.search.lookup(case.query, case.device_profession)
            names = lookup.selected_names
            target = normalize_device_name(case.target)
            normalized_names = [normalize_device_name(name) for name in names]
            rank = normalized_names.index(target) + 1 if target in normalized_names else None
            query = normalize_device_name(case.query)
            results.append(
                DeviceTermCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    like_hit=query in target,
                    semantic_rank=rank,
                    semantic_top1_hit=rank == 1,
                    semantic_top3_hit=rank is not None and rank <= 3,
                    semantic_top5_hit=rank is not None and rank <= 5,
                    candidates=names,
                    error_code=lookup.error_code,
                    embedding_latency_ms=lookup.embedding_latency_ms,
                    qdrant_latency_ms=lookup.qdrant_latency_ms,
                    total_latency_ms=lookup.total_latency_ms,
                )
            )
        total = len(results)
        denominator = total or 1
        ordered_total_latency = sorted(item.total_latency_ms for item in results)
        p95_index = max(0, math.ceil(0.95 * len(ordered_total_latency)) - 1)
        return DeviceTermEvaluationReport(
            total_cases=total,
            like_hit_rate=sum(item.like_hit for item in results) / denominator,
            semantic_top1_hit_rate=(
                sum(item.semantic_top1_hit for item in results) / denominator
            ),
            semantic_top3_hit_rate=(
                sum(item.semantic_top3_hit for item in results) / denominator
            ),
            semantic_top5_hit_rate=(
                sum(item.semantic_top5_hit for item in results) / denominator
            ),
            average_embedding_latency_ms=(
                sum(item.embedding_latency_ms for item in results) / denominator
            ),
            average_qdrant_latency_ms=(
                sum(item.qdrant_latency_ms for item in results) / denominator
            ),
            average_total_latency_ms=(
                sum(item.total_latency_ms for item in results) / denominator
            ),
            p95_total_latency_ms=(
                ordered_total_latency[p95_index] if ordered_total_latency else 0
            ),
            results=results,
        )
