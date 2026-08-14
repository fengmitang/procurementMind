from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_app.graph.schemas import RouteType


class AgentAcceptanceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1)
    expected_route: RouteType
    expected_tool: str | None = None
    platform_user_id: str = "test-user-01"


class AgentAcceptanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    question: str
    expected_route: RouteType
    expected_tool: str | None = None
    actual_route: str | None = None
    route_correct: bool = False
    actual_tools: list[str] = Field(default_factory=list)
    tool_correct: bool = False
    success: bool = False
    model_call_count: int = Field(default=0, ge=0)
    successful_model_call_count: int = Field(default=0, ge=0)
    model_input_tokens: int | None = Field(default=None, ge=0)
    model_output_tokens: int | None = Field(default=None, ge=0)
    model_total_tokens: int | None = Field(default=None, ge=0)
    estimated_model_cost: str | None = None
    model_cost_currency: str | None = None
    tool_call_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None
    execution_status: str | None = None
    performance: dict[str, int] = Field(default_factory=dict)
    stage_timing_ms: dict[str, int] = Field(default_factory=dict)


def load_agent_acceptance_cases(path: Path) -> list[AgentAcceptanceCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"评测文件必须是 JSON 数组：{path}")
    cases = [AgentAcceptanceCase.model_validate(item) for item in data]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("评测 case_id 必须唯一")
    return cases


def percentile(values: list[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 2)


def summarize_agent_acceptance(results: list[AgentAcceptanceResult]) -> dict:
    total = len(results)
    durations = [item.duration_ms for item in results]

    def ratio(count: int, denominator: int = total) -> float:
        return round(count / denominator, 4) if denominator else 0.0

    grouped: dict[str, list[AgentAcceptanceResult]] = defaultdict(list)
    for result in results:
        grouped[result.category].append(result)

    categories = {}
    for category, items in sorted(grouped.items()):
        count = len(items)
        tool_items = [item for item in items if item.expected_tool is not None]
        categories[category] = {
            "total_cases": count,
            "success_rate": ratio(sum(item.success for item in items), count),
            "route_accuracy": ratio(sum(item.route_correct for item in items), count),
            "tool_accuracy": ratio(sum(item.tool_correct for item in tool_items), len(tool_items))
            if tool_items
            else None,
            "average_duration_ms": round(sum(item.duration_ms for item in items) / count, 2),
            "average_model_call_count": round(
                sum(item.model_call_count for item in items) / count, 2
            ),
            "average_tool_call_count": round(
                sum(item.tool_call_count for item in items) / count, 2
            ),
        }

    tool_results = [item for item in results if item.expected_tool is not None]
    reported_costs = [item for item in results if item.estimated_model_cost is not None]
    return {
        "report_version": "agent-acceptance-v0.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "total_cases": total,
        "task_success_rate": ratio(sum(item.success for item in results)),
        "route_accuracy": ratio(sum(item.route_correct for item in results)),
        "tool_evaluated_cases": len(tool_results),
        "tool_accuracy": ratio(sum(item.tool_correct for item in tool_results), len(tool_results))
        if tool_results
        else None,
        "average_duration_ms": round(sum(durations) / total, 2) if total else 0.0,
        "p50_duration_ms": percentile(durations, 0.5),
        "p95_duration_ms": percentile(durations, 0.95),
        "average_model_call_count": round(sum(item.model_call_count for item in results) / total, 2)
        if total
        else 0.0,
        "average_successful_model_call_count": round(
            sum(item.successful_model_call_count for item in results) / total, 2
        )
        if total
        else 0.0,
        "model_cost_available": len(reported_costs) == total and total > 0,
        "model_cost_reported_cases": len(reported_costs),
        "average_tool_call_count": round(sum(item.tool_call_count for item in results) / total, 2)
        if total
        else 0.0,
        "categories": categories,
        "failed_cases": [
            {
                "case_id": item.case_id,
                "category": item.category,
                "actual_route": item.actual_route,
                "actual_tools": item.actual_tools,
                "execution_status": item.execution_status,
                "error": item.error,
            }
            for item in results
            if not item.success
        ],
    }
