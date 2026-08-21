"""Run the representative Agent acceptance set and RAG retrieval evaluation."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.clients.errors import ProcurementBackendError  # noqa: E402
from agent_app.clients.procurement_backend import ProcurementBackendClient  # noqa: E402
from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.evaluation.acceptance import (  # noqa: E402
    AgentAcceptanceCase,
    AgentAcceptanceResult,
    evaluate_result_assertion,
    load_agent_acceptance_cases,
    summarize_agent_acceptance,
)
from agent_app.evaluation.rag import (  # noqa: E402
    RAGEvaluator,
    RetrievalStrategy,
    load_rag_evaluation_cases,
)
from agent_app.rag.models import initialize_rag_providers  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from agent_app.rag.retriever import KnowledgeRetriever  # noqa: E402
from agent_app.schemas.analytics import AnalyticsQueryInput  # noqa: E402
from agent_app.schemas.backend import BackendIdentity, RequirementDetailData  # noqa: E402
from app.core.development_identities import resolve_development_platform_type  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "agent_acceptance_evaluation_v0.2.json",
    )
    parser.add_argument("--agent-url", default="http://127.0.0.1:8100")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts" / "agent-acceptance")
    parser.add_argument("--skip-rag", action="store_true")
    parser.add_argument("--only-rag", action="store_true")
    parser.add_argument(
        "--rag-cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "rag_acceptance_evaluation_v0.2.json",
    )
    parser.add_argument("--rag-k", type=int, default=5)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat 必须大于 0")
    if args.warmup < 0:
        parser.error("--warmup 不能小于 0")
    return args


def identity_for(user_id: str) -> BackendIdentity:
    platform_type = resolve_development_platform_type(user_id)
    if platform_type is None:
        raise RuntimeError(f"评测用户不在开发身份白名单中：{user_id}")
    return BackendIdentity(platform_type=platform_type, platform_user_id=user_id)


def stage_timings(data: dict[str, Any]) -> dict[str, int]:
    totals = {"model": 0, "retrieval": 0, "rerank": 0, "tool": 0}
    for event in (data.get("execution") or {}).get("trace_events") or []:
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        duration = int(event.get("duration_ms") or 0)
        if model_attempted(event):
            totals["model"] += int(result.get("latency_ms") or duration)
        if event.get("name") == "knowledge_retrieval":
            timings = result.get("rag_timings") or {}
            totals["retrieval"] += int(timings.get("retrieval_wall_ms") or duration)
            totals["rerank"] += int(timings.get("rerank_ms") or 0)
    totals["tool"] = sum(
        int(item.get("duration_ms") or 0)
        for item in (data.get("execution") or {}).get("tools") or []
    )
    return totals


def model_attempted(event: dict[str, Any]) -> bool:
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    if result.get("model_used") is True:
        return True
    if event.get("name") in {"model_router", "model_planner", "form_extract"}:
        return True
    return event.get("name") in {"compose_answer", "review"} and str(
        event.get("error_code") or ""
    ).startswith("MODEL_")


def detail_values(detail: RequirementDetailData) -> dict[str, Any]:
    applicant = detail.applicant_fields
    return {
        "requirement_id": detail.requirement_id,
        "requirement_no": detail.requirement_no,
        "status": detail.status,
        "handler_name": detail.current_handler.name if detail.current_handler else None,
        "device_name": applicant.device_name,
        "device_profession": applicant.device_profession,
        "brand": applicant.brand,
        "model": applicant.model,
        "quantity": applicant.quantity,
        "unit": applicant.unit,
        "building_name": detail.building.building_name,
        "supplier_name": (
            detail.purchase_execution.supplier_name if detail.purchase_execution else None
        ),
    }


async def discover_ground_truth(
    backend: ProcurementBackendClient,
    cases: list[AgentAcceptanceCase],
) -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    users = {
        case.platform_user_id
        for case in cases
        if "{{" in case.question
        or case.expected_route.value in {"REALTIME_BUSINESS", "RISK_INVESTIGATION", "HYBRID"}
    }
    for user_id in sorted(users):
        trace_id = f"agent-eval-discovery-{uuid4().hex}"
        resolved_user_id = user_id
        identity = identity_for(resolved_user_id)
        try:
            records = await backend.search_purchase_records(
                identity, trace_id, page=1, page_size=20
            )
        except ProcurementBackendError as exc:
            raise RuntimeError(
                f"评测用户 {user_id} 动态数据发现失败：{exc.code}: {exc.message}"
            ) from exc
        if not records.items and user_id == "demo_user_001":
            resolved_user_id = "demo_user_006"
            identity = identity_for(resolved_user_id)
            records = await backend.search_purchase_records(
                identity, trace_id, page=1, page_size=20
            )
        if not records.items:
            raise RuntimeError(f"用户 {user_id} 当前没有可用于评测的采购申请")
        selected = next(
            (item for item in records.items if item.status not in {"DRAFT", "REJECTED"}),
            records.items[0],
        )
        detail = await backend.get_requirement(identity, selected.requirement_id, trace_id)
        timeline = await backend.get_requirement_timeline(
            identity, selected.requirement_id, trace_id
        )
        values = detail_values(detail)
        values["timeline_action"] = timeline.items[0].action_type if timeline.items else None
        discovered[user_id] = {
            "detail": detail,
            "values": values,
            "resolved_user_id": resolved_user_id,
        }
    return discovered


def render_templates(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(replacement or ""))
        return rendered
    if isinstance(value, list):
        return [render_templates(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render_templates(item, variables) for key, item in value.items()}
    return value


async def ground_truth_for_response(
    backend: ProcurementBackendClient,
    case: AgentAcceptanceCase,
    data: dict[str, Any],
    discovered: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assertion = case.result_assertion
    if assertion.kind in {"REALTIME_BUSINESS", "HYBRID"}:
        values = discovered.get(case.platform_user_id, {}).get("values", {})
        return {"values": values, "required_values": assertion.ground_truth_fields}
    if assertion.kind == "COMPLEX_QUERY":
        tool = next(
            (
                item
                for item in (data.get("execution") or {}).get("tools") or []
                if item.get("name") == "query_purchase_analytics" and item.get("success")
            ),
            None,
        )
        query_data = ((tool or {}).get("arguments") or {}).get("query")
        if not isinstance(query_data, dict):
            return {}
        truth = await backend.query_purchase_analytics(
            identity_for(case.platform_user_id),
            f"agent-eval-truth-{uuid4().hex}",
            AnalyticsQueryInput.model_validate(query_data),
        )
        return {
            "summary": truth.summary.model_dump(mode="json"),
            "groups": [item.model_dump(mode="json") for item in truth.groups],
        }
    if assertion.kind == "RISK_INVESTIGATION":
        detail = discovered.get(case.platform_user_id, {}).get("detail")
        if detail is None:
            return {}
        truth = await backend.get_requirement_risk_signals(
            identity_for(case.platform_user_id),
            detail.requirement_id,
            f"agent-eval-truth-{uuid4().hex}",
        )
        return {"matched_risk_codes": [item.risk_code for item in truth.signals if item.matched]}
    return {}


async def run_case(
    client: httpx.AsyncClient,
    backend: ProcurementBackendClient,
    case: AgentAcceptanceCase,
    discovered: dict[str, dict[str, Any]],
    run_id: str,
) -> AgentAcceptanceResult:
    variables = discovered.get(case.platform_user_id, {}).get("values", {})
    resolved_user_id = discovered.get(case.platform_user_id, {}).get(
        "resolved_user_id", case.platform_user_id
    )
    question = render_templates(case.question, variables)
    assertion = case.result_assertion.model_copy(
        update={
            "expected_contains": render_templates(
                case.result_assertion.expected_contains, variables
            ),
            "expected_any": render_templates(case.result_assertion.expected_any, variables),
            "expected_not_contains": render_templates(
                case.result_assertion.expected_not_contains, variables
            ),
            "expected_fields": render_templates(case.result_assertion.expected_fields, variables),
        }
    )
    started = time.perf_counter()
    conversation_id: int | None = None
    error: str | None = None
    data: dict[str, Any] = {}
    try:
        response = await client.post(
            "/api/v1/chat",
            headers={"X-Request-Id": f"acceptance-{uuid4().hex}"},
            json={
                "platform_type": identity_for(resolved_user_id).platform_type,
                "platform_user_id": resolved_user_id,
                "message": question,
                "external_conversation_id": f"ACCEPTANCE-{run_id}-{case.case_id}",
                "external_message_id": f"acceptance-{run_id}-{case.case_id}",
            },
        )
        response.raise_for_status()
        envelope = response.json()
        if not envelope.get("success"):
            raise RuntimeError(f"{envelope.get('code')}: {envelope.get('message')}")
        data = envelope.get("data") or {}
        if data.get("conversation_id") is not None:
            conversation_id = int(data["conversation_id"])
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    duration_ms = max(0, round((time.perf_counter() - started) * 1000))

    execution = data.get("execution") or {}
    tools = execution.get("tools") or []
    actual_tools = [str(item.get("name")) for item in tools if item.get("name")]
    failed_tools = [str(item.get("name")) for item in tools if not item.get("success")]
    actual_route = data.get("route")
    route_correct = actual_route == case.expected_route.value
    skill_correct = (
        case.expected_skill is None
        or (data.get("recommendation") or {}).get("skill_id") == case.expected_skill
    )
    tool_skill_evaluated = bool(case.expected_tools or case.forbidden_tools or case.expected_skill)
    tool_correct = (
        set(case.expected_tools).issubset(actual_tools)
        and not set(case.forbidden_tools).intersection(actual_tools)
        and skill_correct
    )
    graph_errors = execution.get("errors") or []
    execution_status = execution.get("status")
    if error is None and graph_errors:
        error = "; ".join(f"{item.get('code')}: {item.get('message')}" for item in graph_errors)
    truth = await ground_truth_for_response(backend, case, data, discovered) if data else {}
    result_correct, assertion_failures, snapshot = evaluate_result_assertion(
        assertion, data, ground_truth=truth
    )
    execution_complete = (
        execution_status == "COMPLETE" and not graph_errors and not failed_tools and error is None
    )
    result = AgentAcceptanceResult(
        case_id=case.case_id,
        category=case.category,
        question=question,
        evaluated_platform_user_id=resolved_user_id,
        expected_route=case.expected_route,
        expected_tools=case.expected_tools,
        forbidden_tools=case.forbidden_tools,
        expected_skill=case.expected_skill,
        expected_result=assertion.model_dump(mode="json"),
        actual_route=actual_route,
        route_correct=route_correct,
        actual_tools=actual_tools,
        failed_tools=failed_tools,
        tool_skill_evaluated=tool_skill_evaluated,
        tool_correct=tool_correct,
        result_correct=result_correct,
        execution_complete=execution_complete,
        success=route_correct and tool_correct and result_correct and execution_complete,
        assertion_failures=assertion_failures,
        actual_result=snapshot,
        model_call_count=sum(
            model_attempted(event) for event in execution.get("trace_events") or []
        ),
        successful_model_call_count=int(
            (execution.get("model_usage") or {}).get("call_count") or 0
        ),
        model_input_tokens=(execution.get("model_usage") or {}).get("input_tokens"),
        model_output_tokens=(execution.get("model_usage") or {}).get("output_tokens"),
        model_total_tokens=(execution.get("model_usage") or {}).get("total_tokens"),
        estimated_model_cost=(execution.get("model_usage") or {}).get("estimated_cost"),
        model_cost_currency=(execution.get("model_usage") or {}).get("currency"),
        tool_call_count=int(data.get("tool_call_count") or len(actual_tools)),
        duration_ms=duration_ms,
        error=error,
        execution_status=execution_status,
        performance={key: int(value) for key, value in (data.get("performance") or {}).items()},
        stage_timing_ms=stage_timings(data),
    )
    if conversation_id is not None:
        try:
            await backend.complete_conversation(
                identity_for(resolved_user_id),
                conversation_id,
                f"agent-eval-complete-{uuid4().hex}",
            )
        except Exception as exc:
            result.error = result.error or f"cleanup: {type(exc).__name__}: {exc}"
            result.execution_complete = False
            result.success = False
    return result


def write_agent_outputs(
    output_dir: Path, run_id: str, results: list[AgentAcceptanceResult], summary: dict
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_json = output_dir / f"agent-acceptance-{run_id}.json"
    raw_csv = output_dir / f"agent-acceptance-{run_id}.csv"
    summary_json = output_dir / f"agent-acceptance-{run_id}-summary.json"
    payload = [item.model_dump(mode="json") for item in results]
    raw_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fieldnames = list(payload[0]) if payload else list(AgentAcceptanceResult.model_fields)
    with raw_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )
    return {"raw_json": str(raw_json), "raw_csv": str(raw_csv), "summary_json": str(summary_json)}


async def run_rag(args: argparse.Namespace, run_id: str) -> tuple[dict, str]:
    settings = get_agent_settings()
    providers = initialize_rag_providers(settings)
    if providers is None:
        raise RuntimeError("RAG Provider 未配置")
    store = QdrantKnowledgeStore(settings)
    try:
        await store.ensure_collection()
        retriever = KnowledgeRetriever(
            settings=settings,
            session_factory=async_session_factory,
            model_provider=providers,
            qdrant_store=store,
        )
        report = await RAGEvaluator(evaluation_k=args.rag_k).run(
            load_rag_evaluation_cases(args.rag_cases), retriever
        )
        evaluated = [
            case for case in report.cases if case.retrieval_executed and case.relevant_parent_ids
        ]

        def hit_rate(strategy: RetrievalStrategy) -> float:
            return (
                round(
                    sum(case.strategies[strategy].recall_at_k > 0 for case in evaluated)
                    / len(evaluated),
                    4,
                )
                if evaluated
                else 0.0
            )

        payload = report.model_dump(mode="json")
        payload["acceptance_summary"] = {
            "total_cases": report.total_cases,
            "evaluated_cases": len(evaluated),
            "citation_accuracy": report.citation_accuracy,
            "negative_accuracy": report.negative_accuracy,
            "strategies": {
                strategy.value: {
                    "hit_at_5": hit_rate(strategy),
                    "recall_at_5": report.strategies[strategy].recall_at_k,
                    "mrr": report.strategies[strategy].mrr,
                }
                for strategy in RetrievalStrategy
            },
            "missed_cases": {
                strategy.value: [
                    case.case_id for case in evaluated if case.strategies[strategy].recall_at_k == 0
                ]
                for strategy in RetrievalStrategy
            },
        }
        path = args.output_dir / f"rag-acceptance-{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload["acceptance_summary"], str(path)
    finally:
        await store.close()
        providers.close()


def repeat_summary(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(summaries) < 2:
        return None
    fields = (
        "task_success_rate",
        "result_correctness_rate",
        "route_accuracy",
        "average_duration_ms",
    )
    return {
        field: {
            "mean": round(statistics.mean(item[field] for item in summaries), 4),
            "min": min(item[field] for item in summaries),
            "max": max(item[field] for item in summaries),
            "stdev": round(statistics.pstdev(item[field] for item in summaries), 4),
        }
        for field in fields
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    base_run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.only_rag:
        try:
            rag_summary, rag_output = await run_rag(args, base_run_id)
            return {"rag": rag_summary, "outputs": {"rag_json": rag_output}}
        finally:
            await engine.dispose()
    cases = load_agent_acceptance_cases(args.cases)
    settings = get_agent_settings()
    backend = ProcurementBackendClient(settings)
    try:
        discovered = await discover_ground_truth(backend, cases)
        run_summaries: list[dict[str, Any]] = []
        all_outputs: list[dict[str, str]] = []
        async with httpx.AsyncClient(base_url=args.agent_url, timeout=args.timeout) as client:
            for index, case in enumerate(cases[: args.warmup], start=1):
                print(f"[warmup {index}/{min(args.warmup, len(cases))}] {case.case_id}", flush=True)
                await run_case(client, backend, case, discovered, f"warmup-{base_run_id}")
            for repeat_index in range(1, args.repeat + 1):
                run_id = f"{base_run_id}-r{repeat_index}"
                results: list[AgentAcceptanceResult] = []
                for index, case in enumerate(cases, start=1):
                    result = await run_case(client, backend, case, discovered, run_id)
                    results.append(result)
                    print(
                        f"[{index:02d}/{len(cases)}] {case.case_id}: success={result.success} "
                        f"route={result.actual_route} tools={result.actual_tools} "
                        f"duration_ms={result.duration_ms}",
                        flush=True,
                    )
                summary = summarize_agent_acceptance(results)
                run_summaries.append(summary)
                all_outputs.append(write_agent_outputs(args.output_dir, run_id, results, summary))
        final: dict[str, Any] = {
            "agent": run_summaries[0] if len(run_summaries) == 1 else run_summaries,
            "repeat_summary": repeat_summary(run_summaries),
            "outputs": {"agent_runs": all_outputs},
        }
        if not args.skip_rag:
            try:
                rag_summary, rag_output = await run_rag(args, base_run_id)
                final["rag"] = rag_summary
                final["outputs"]["rag_json"] = rag_output
            except Exception as exc:
                final["rag"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        return final
    finally:
        await backend.aclose()
        await engine.dispose()


def main() -> int:
    args = parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
