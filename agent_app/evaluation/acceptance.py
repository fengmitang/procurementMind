from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_app.graph.schemas import RouteType


class ResultAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "KNOWLEDGE",
        "REALTIME_BUSINESS",
        "COMPLEX_QUERY",
        "RISK_INVESTIGATION",
        "FORM_PREFILL",
        "RECOMMENDATION",
        "HYBRID",
    ]
    expected_contains: list[str] = Field(default_factory=list)
    expected_any: list[list[str]] = Field(default_factory=list)
    expected_not_contains: list[str] = Field(default_factory=list)
    expected_fields: dict[str, Any] = Field(default_factory=dict)
    ground_truth_fields: list[str] = Field(default_factory=list)
    missing_fields_contains: list[str] = Field(default_factory=list)
    classification_status: str | None = None
    candidate_professions: list[str] = Field(default_factory=list)
    min_evidence_count: int = Field(default=0, ge=0)
    min_citation_count: int = Field(default=0, ge=0)
    required_evidence_kinds: list[str] = Field(default_factory=list)
    expected_profile: str | None = None
    expected_recommendation_type: str | None = None
    min_candidates: int = Field(default=0, ge=0)
    clarification_required: bool | None = None


class AgentAcceptanceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1)
    expected_route: RouteType
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_skill: str | None = None
    platform_user_id: str = "test-user-01"
    boundary: bool = False
    result_assertion: ResultAssertion


class AgentAcceptanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    question: str
    evaluated_platform_user_id: str | None = None
    expected_route: RouteType
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_skill: str | None = None
    expected_result: dict[str, Any] = Field(default_factory=dict)
    actual_route: str | None = None
    route_correct: bool = False
    actual_tools: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    tool_skill_evaluated: bool = False
    tool_correct: bool = False
    result_correct: bool = False
    execution_complete: bool = False
    success: bool = False
    assertion_failures: list[str] = Field(default_factory=list)
    actual_result: dict[str, Any] = Field(default_factory=dict)
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


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return str(value) if value is not None else None


_BUSINESS_VALUE_LABELS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("草稿",),
    "PENDING_MANAGER_REVIEW": ("待楼长审核",),
    "REJECTED": ("已驳回",),
    "PENDING_PURCHASE": ("待采购",),
    "PENDING_WAREHOUSE": ("待入库",),
    "COMPLETED": ("已完成",),
}


def _output_contains_value(value: Any, reply: str, serialized: str) -> bool:
    if value is None:
        return True
    candidates = (str(value), *_BUSINESS_VALUE_LABELS.get(str(value), ()))
    return any(candidate in serialized or candidate in reply for candidate in candidates)


def _knowledge_metrics(data: dict[str, Any]) -> tuple[bool, int, int]:
    """Read the public chat contract, which exposes sources instead of full RAG chunks."""
    knowledge = data.get("knowledge") or {}
    sources = data.get("knowledge_sources") or knowledge.get("citations") or []
    evidence_count = int(data.get("evidence_count") or len(knowledge.get("evidences") or []))
    answerable = bool(knowledge.get("answerable")) if knowledge else evidence_count > 0
    return answerable, len(sources), evidence_count


def evaluate_result_assertion(
    assertion: ResultAssertion,
    data: dict[str, Any],
    *,
    ground_truth: dict[str, Any] | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    reply = str(data.get("reply") or "")
    for expected in assertion.expected_contains:
        if expected not in reply:
            failures.append(f"reply missing: {expected}")
    for alternatives in assertion.expected_any:
        if alternatives and not any(value in reply for value in alternatives):
            failures.append(f"reply missing any of: {alternatives}")
    for forbidden in assertion.expected_not_contains:
        if forbidden in reply:
            failures.append(f"reply contains forbidden: {forbidden}")
    if assertion.kind != "FORM_PREFILL":
        for path, expected in assertion.expected_fields.items():
            actual = get_path(data, path)
            if _normalized(actual) != _normalized(expected):
                failures.append(f"{path}: expected={expected!r}, actual={actual!r}")

    snapshot: dict[str, Any] = {"reply": reply}
    if assertion.kind == "KNOWLEDGE":
        answerable, citation_count, evidence_count = _knowledge_metrics(data)
        if not answerable:
            failures.append("knowledge.answerable is not true")
        if citation_count < assertion.min_citation_count:
            failures.append(
                f"citations: expected>={assertion.min_citation_count}, actual={citation_count}"
            )
        if evidence_count < assertion.min_evidence_count:
            failures.append(
                "knowledge evidence: "
                f"expected>={assertion.min_evidence_count}, actual={evidence_count}"
            )
        snapshot.update(
            answerable=answerable,
            citation_count=citation_count,
            evidence_count=evidence_count,
        )
    elif assertion.kind == "REALTIME_BUSINESS":
        truth = ground_truth or {}
        serialized = json.dumps(data.get("business_results") or [], ensure_ascii=False)
        for key in truth.get("required_values", []):
            value = truth.get("values", {}).get(key)
            if not _output_contains_value(value, reply, serialized):
                failures.append(f"business result missing ground truth {key}={value}")
        snapshot.update(
            ground_truth=truth.get("values"), business_results=data.get("business_results")
        )
    elif assertion.kind == "COMPLEX_QUERY":
        analysis = data.get("analysis") or {}
        truth = ground_truth or {}
        if _normalized(analysis.get("summary")) != _normalized(truth.get("summary")):
            failures.append("analysis.summary differs from backend ground truth")
        if _normalized(analysis.get("groups")) != _normalized(truth.get("groups")):
            failures.append("analysis.groups differs from backend ground truth")
        snapshot.update(summary=analysis.get("summary"), groups=analysis.get("groups"))
    elif assertion.kind == "RISK_INVESTIGATION":
        investigation = data.get("risk_investigation") or {}
        evidence = investigation.get("evidence") or []
        kinds = {item.get("kind") for item in evidence if item.get("status") == "SUCCESS"}
        for kind in assertion.required_evidence_kinds:
            if kind not in kinds:
                failures.append(f"missing successful risk evidence: {kind}")
        if not investigation.get("complete"):
            failures.append("risk investigation is not complete")
        truth_codes = set((ground_truth or {}).get("matched_risk_codes") or [])
        actual_codes = {
            item.get("risk_code")
            for item in investigation.get("summary_items") or []
            if item.get("backend_rule_matched")
        }
        if truth_codes != actual_codes:
            failures.append(
                "matched risk codes differ: "
                f"expected={sorted(truth_codes)}, actual={sorted(actual_codes)}"
            )
        snapshot.update(
            complete=investigation.get("complete"), matched_risk_codes=sorted(actual_codes)
        )
    elif assertion.kind == "FORM_PREFILL":
        draft = data.get("form_draft") or {}
        classification = data.get("form_classification") or {}
        missing = data.get("form_missing_fields") or []
        if (
            assertion.classification_status
            and classification.get("classification_status") != assertion.classification_status
        ):
            failures.append(
                "classification_status: "
                f"expected={assertion.classification_status}, "
                f"actual={classification.get('classification_status')}"
            )
        if assertion.candidate_professions and not set(assertion.candidate_professions).issubset(
            set(classification.get("candidate_professions") or [])
        ):
            failures.append("candidate_professions missing expected values")
        for field, expected in assertion.expected_fields.items():
            actual = draft.get(field)
            if _normalized(actual) != _normalized(expected):
                failures.append(f"form_draft.{field}: expected={expected!r}, actual={actual!r}")
        for field in assertion.missing_fields_contains:
            if field not in missing:
                failures.append(f"form missing_fields does not include {field}")
        snapshot.update(form_draft=draft, classification=classification, missing_fields=missing)
    elif assertion.kind == "RECOMMENDATION":
        recommendation = data.get("recommendation") or {}
        candidates = recommendation.get("candidates") or []
        evidence = recommendation.get("evidence") or []
        if recommendation.get("skill_id") != "procurement_recommendation":
            failures.append("recommendation skill output missing")
        if (
            assertion.expected_profile
            and recommendation.get("profile") != assertion.expected_profile
        ):
            failures.append(
                f"profile: expected={assertion.expected_profile}, "
                f"actual={recommendation.get('profile')}"
            )
        if (
            assertion.expected_recommendation_type
            and recommendation.get("recommendation_type") != assertion.expected_recommendation_type
        ):
            failures.append("recommendation_type differs")
        if len(candidates) < assertion.min_candidates:
            failures.append(
                f"candidates: expected>={assertion.min_candidates}, actual={len(candidates)}"
            )
        if len(evidence) < assertion.min_evidence_count:
            failures.append(
                f"evidence: expected>={assertion.min_evidence_count}, actual={len(evidence)}"
            )
        if (
            assertion.clarification_required is not None
            and recommendation.get("clarification_required") is not assertion.clarification_required
        ):
            failures.append("clarification_required differs")
        evidence_refs = {item.get("reference_id") for item in evidence}
        for candidate in candidates:
            if not set(candidate.get("evidence_refs") or []).issubset(evidence_refs):
                failures.append(
                    f"candidate {candidate.get('candidate_id')} has unsupported evidence"
                )
        snapshot.update(
            profile=recommendation.get("profile"),
            recommendation_type=recommendation.get("recommendation_type"),
            candidate_titles=[item.get("title") for item in candidates],
            evidence_count=len(evidence),
            clarification_required=recommendation.get("clarification_required"),
        )
    elif assertion.kind == "HYBRID":
        answerable, citation_count, evidence_count = _knowledge_metrics(data)
        if not answerable or citation_count == 0:
            failures.append("hybrid knowledge evidence/citation missing")
        truth = ground_truth or {}
        serialized = json.dumps(data.get("business_results") or [], ensure_ascii=False)
        for key in truth.get("required_values", []):
            value = truth.get("values", {}).get(key)
            if not _output_contains_value(value, reply, serialized):
                failures.append(f"hybrid business result missing {key}={value}")
        snapshot.update(
            citation_count=citation_count,
            evidence_count=evidence_count,
            ground_truth=truth.get("values"),
        )
    return not failures, failures, snapshot


def summarize_agent_acceptance(results: list[AgentAcceptanceResult]) -> dict[str, Any]:
    total = len(results)

    def ratio(count: int, denominator: int) -> float:
        return round(count / denominator, 4) if denominator else 0.0

    def metrics(items: list[AgentAcceptanceResult]) -> dict[str, Any]:
        count = len(items)
        durations = [item.duration_ms for item in items]
        tool_items = [item for item in items if item.tool_skill_evaluated]
        return {
            "total_cases": count,
            "task_success_rate": ratio(sum(item.success for item in items), count),
            "result_correctness_rate": ratio(sum(item.result_correct for item in items), count),
            "route_accuracy": ratio(sum(item.route_correct for item in items), count),
            "tool_skill_accuracy": (
                ratio(sum(item.tool_correct for item in tool_items), len(tool_items))
                if tool_items
                else None
            ),
            "average_duration_ms": round(sum(durations) / count, 2) if count else 0.0,
            "p50_duration_ms": percentile(durations, 0.5),
            "p95_duration_ms": percentile(durations, 0.95),
            "average_model_call_count": (
                round(sum(item.model_call_count for item in items) / count, 2) if count else 0.0
            ),
            "average_tool_call_count": (
                round(sum(item.tool_call_count for item in items) / count, 2) if count else 0.0
            ),
        }

    grouped: dict[str, list[AgentAcceptanceResult]] = defaultdict(list)
    for result in results:
        grouped[result.category].append(result)
    tool_items = [item for item in results if item.tool_skill_evaluated]
    all_tool_calls = sum(item.tool_call_count for item in results)
    failed_tool_calls = sum(len(item.failed_tools) for item in results)
    tool_counts = Counter(tool for item in results for tool in item.actual_tools)
    confusion = Counter(
        (item.expected_route.value, item.actual_route or "NONE")
        for item in results
        if not item.route_correct
    )
    model_counts = Counter(
        "0" if item.model_call_count == 0 else "1" if item.model_call_count == 1 else ">1"
        for item in results
    )
    reported_costs = [item for item in results if item.estimated_model_cost is not None]
    return {
        "report_version": "agent-acceptance-v0.2",
        "generated_at": datetime.now(UTC).isoformat(),
        **metrics(results),
        "tool_evaluated_cases": len(tool_items),
        "tool_failure_rate": ratio(failed_tool_calls, all_tool_calls),
        "tool_call_counts": dict(sorted(tool_counts.items())),
        "model_call_distribution": {
            key: ratio(model_counts[key], total) for key in ("0", "1", ">1")
        },
        "route_confusion": [
            {"expected": expected, "actual": actual, "count": count}
            for (expected, actual), count in sorted(confusion.items())
        ],
        "average_successful_model_call_count": (
            round(sum(item.successful_model_call_count for item in results) / total, 2)
            if total
            else 0.0
        ),
        "model_cost_available": len(reported_costs) == total and total > 0,
        "model_cost_reported_cases": len(reported_costs),
        "categories": {category: metrics(items) for category, items in sorted(grouped.items())},
        "tool_selection_error_cases": [
            item.case_id for item in tool_items if not item.tool_correct
        ],
        "failed_cases": [
            {
                "case_id": item.case_id,
                "category": item.category,
                "question": item.question,
                "evaluated_platform_user_id": item.evaluated_platform_user_id,
                "expected_route": item.expected_route.value,
                "expected_tools": item.expected_tools,
                "expected_result": item.expected_result,
                "actual_route": item.actual_route,
                "actual_tools": item.actual_tools,
                "actual_result": item.actual_result,
                "assertion_failures": item.assertion_failures,
                "execution_status": item.execution_status,
                "error": item.error,
                "duration_ms": item.duration_ms,
                "model_call_count": item.model_call_count,
                "tool_call_count": item.tool_call_count,
            }
            for item in results
            if not item.success
        ],
    }
