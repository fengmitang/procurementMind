"""Run the fixed Agent API acceptance set and optional lightweight RAG Hit@5 evaluation."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
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

from agent_app.clients.procurement_backend import ProcurementBackendClient  # noqa: E402
from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.evaluation.acceptance import (  # noqa: E402
    AgentAcceptanceCase,
    AgentAcceptanceResult,
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
from agent_app.schemas.backend import BackendIdentity  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "agent_acceptance_evaluation_v0.1.json",
    )
    parser.add_argument("--agent-url", default="http://127.0.0.1:8100")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts" / "agent-acceptance")
    parser.add_argument("--skip-rag", action="store_true")
    parser.add_argument("--only-rag", action="store_true")
    parser.add_argument(
        "--rag-cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "rag_acceptance_evaluation_v0.1.json",
    )
    parser.add_argument("--rag-k", type=int, default=5)
    return parser.parse_args()


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
    if event.get("name") in {"model_router", "model_planner"}:
        return True
    return event.get("name") in {"compose_answer", "review"} and str(
        event.get("error_code") or ""
    ).startswith("MODEL_")


async def discover_requirement_ids(
    backend: ProcurementBackendClient, cases: list[AgentAcceptanceCase]
) -> dict[str, int]:
    ids: dict[str, int] = {}
    users_requiring_ids = {
        case.platform_user_id for case in cases if "{{requirement_id}}" in case.question
    }
    for user_id in sorted(users_requiring_ids):
        identity = BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id=user_id)
        records = await backend.search_purchase_records(
            identity, f"agent-eval-discovery-{uuid4().hex}", page=1, page_size=1
        )
        if not records.items:
            raise RuntimeError(f"用户 {user_id} 当前没有可用于评测的采购申请")
        ids[user_id] = records.items[0].requirement_id
    return ids


async def run_case(
    client: httpx.AsyncClient,
    backend: ProcurementBackendClient,
    case: AgentAcceptanceCase,
    requirement_ids: dict[str, int],
    run_id: str,
) -> AgentAcceptanceResult:
    question = case.question.replace(
        "{{requirement_id}}", str(requirement_ids.get(case.platform_user_id, ""))
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
                "platform_type": "TEST_PLATFORM",
                "platform_user_id": case.platform_user_id,
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
    except Exception as exc:  # Every failed case belongs in the raw report.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))

    execution = data.get("execution") or {}
    actual_tools = [
        str(item.get("name")) for item in execution.get("tools") or [] if item.get("name")
    ]
    actual_route = data.get("route")
    route_correct = actual_route == case.expected_route.value
    tool_correct = case.expected_tool is None or case.expected_tool in actual_tools
    execution_status = execution.get("status")
    graph_errors = execution.get("errors") or []
    trace_events = execution.get("trace_events") or []
    if error is None and graph_errors:
        error = "; ".join(f"{item.get('code')}: {item.get('message')}" for item in graph_errors)
    success = error is None and route_correct and tool_correct and execution_status == "COMPLETE"
    result = AgentAcceptanceResult(
        case_id=case.case_id,
        category=case.category,
        question=question,
        expected_route=case.expected_route,
        expected_tool=case.expected_tool,
        actual_route=actual_route,
        route_correct=route_correct,
        actual_tools=actual_tools,
        tool_correct=tool_correct,
        success=success,
        model_call_count=sum(model_attempted(event) for event in trace_events),
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
                BackendIdentity(
                    platform_type="TEST_PLATFORM", platform_user_id=case.platform_user_id
                ),
                conversation_id,
                f"agent-eval-complete-{uuid4().hex}",
            )
        except Exception as exc:
            result.error = result.error or f"cleanup: {type(exc).__name__}: {exc}"
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
            if not evaluated:
                return 0.0
            return round(
                sum(case.strategies[strategy].recall_at_k > 0 for case in evaluated)
                / len(evaluated),
                4,
            )

        payload = report.model_dump(mode="json")
        payload["acceptance_summary"] = {
            "evaluated_cases": len(evaluated),
            "hit_at_5_before_rerank": hit_rate(RetrievalStrategy.HYBRID),
            "hit_at_5_after_rerank": hit_rate(RetrievalStrategy.HYBRID_RERANKER),
            "mrr_before_rerank": report.strategies[RetrievalStrategy.HYBRID].mrr,
            "mrr_after_rerank": report.strategies[RetrievalStrategy.HYBRID_RERANKER].mrr,
        }
        path = args.output_dir / f"rag-acceptance-{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload["acceptance_summary"], str(path)
    finally:
        await store.close()
        providers.close()


async def run(args: argparse.Namespace) -> dict:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.only_rag:
        try:
            rag_summary, rag_output = await run_rag(args, run_id)
            return {"rag": rag_summary, "outputs": {"rag_json": rag_output}}
        finally:
            await engine.dispose()
    cases = load_agent_acceptance_cases(args.cases)
    settings = get_agent_settings()
    backend = ProcurementBackendClient(settings)
    try:
        requirement_ids = await discover_requirement_ids(backend, cases)
        async with httpx.AsyncClient(base_url=args.agent_url, timeout=args.timeout) as client:
            results = []
            for index, case in enumerate(cases, start=1):
                result = await run_case(client, backend, case, requirement_ids, run_id)
                results.append(result)
                print(
                    f"[{index:02d}/{len(cases)}] {case.case_id}: "
                    f"success={result.success} route={result.actual_route} "
                    f"tools={result.actual_tools} duration_ms={result.duration_ms}",
                    flush=True,
                )
        summary = summarize_agent_acceptance(results)
        outputs = write_agent_outputs(args.output_dir, run_id, results, summary)
        final = {"agent": summary, "outputs": outputs}
        if not args.skip_rag:
            try:
                rag_summary, rag_output = await run_rag(args, run_id)
                final["rag"] = rag_summary
                final["outputs"]["rag_json"] = rag_output
            except Exception as exc:
                final["rag"] = {
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }
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
