"""Measure baseline and optimized Agent latency through the real application stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import AgentSettings  # noqa: E402
from agent_app.graph.router import FirstVersionRouter  # noqa: E402
from agent_app.main import create_agent_app  # noqa: E402
from app.core.gateway_auth import build_gateway_signature  # noqa: E402


@dataclass(frozen=True, slots=True)
class QueryCase:
    case_id: str
    scenario: str
    query: str
    expected_route: str
    requirement_id: int | None = None
    expected_status: str | None = None
    requires_knowledge: bool = False
    expect_answerable: bool = True
    relevant_parent_ids: tuple[str, ...] = ()
    expected_section_terms: tuple[str, ...] = ()


CASES = (
    QueryCase(
        "knowledge-rejection-rule",
        "knowledge",
        "采购申请被驳回后的处理规定是什么？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=(
            "4bf46f2c-f2d5-56a9-b306-b91f29738ade",
            "cc18dc0e-ed01-5b77-b974-c435071eea8d",
            "aaa98cae-1388-56e0-9dec-3d46d0f9b505",
        ),
    ),
    QueryCase(
        "knowledge-colloquial-rejection",
        "knowledge",
        "采购流程里，单子被楼长打回来了咋整？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=(
            "4bf46f2c-f2d5-56a9-b306-b91f29738ade",
            "cc18dc0e-ed01-5b77-b974-c435071eea8d",
            "aaa98cae-1388-56e0-9dec-3d46d0f9b505",
        ),
    ),
    QueryCase(
        "knowledge-device-name",
        "knowledge",
        "采购字段填写规范里，买设备时品名应该怎么写？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=("2b6c1463-5e97-55d7-88ad-34609a33c920",),
    ),
    QueryCase(
        "knowledge-multiple-fields",
        "knowledge",
        "采购字段填写规范中，设备名称和采购数量分别应该怎样填写？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=(
            "2b6c1463-5e97-55d7-88ad-34609a33c920",
            "af74cb36-ce47-5675-8a66-34e18ce0ba81",
        ),
    ),
    QueryCase(
        "knowledge-save-draft",
        "knowledge",
        "草稿没填完能否先保存？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=("5c797e0f-ff73-5b6b-82ab-291ee7ad8a4d",),
    ),
    QueryCase(
        "knowledge-assistant-approval",
        "knowledge",
        "智能助手能否替用户自动审批？",
        "KNOWLEDGE",
        requires_knowledge=True,
        relevant_parent_ids=(
            "31d32b19-7b64-540c-a2c3-b89cb4341af3",
            "a066a0e9-e3e7-5036-a8fd-fa8d089cd13b",
        ),
    ),
    QueryCase(
        "knowledge-negative-annual-leave",
        "knowledge",
        "公司的年假申请制度是什么？",
        "KNOWLEDGE",
        requires_knowledge=True,
        expect_answerable=False,
    ),
    QueryCase(
        "knowledge-brand-model",
        "knowledge",
        "采购填写规定中，品牌和型号必须填写吗？",
        "KNOWLEDGE",
        requires_knowledge=True,
        expected_section_terms=("品牌", "型号"),
    ),
    QueryCase(
        "knowledge-visibility",
        "knowledge",
        "需求人为什么不能查看其他人的采购申请？",
        "KNOWLEDGE",
        requires_knowledge=True,
        expected_section_terms=("可查看范围", "为什么我看不到其他人的采购申请"),
    ),
    QueryCase(
        "knowledge-process",
        "knowledge",
        "采购业务的完整办理流程有哪些步骤？",
        "KNOWLEDGE",
        requires_knowledge=True,
        expected_section_terms=("采购流程", "流程"),
    ),
    QueryCase(
        "realtime-91001",
        "realtime",
        "采购申请 91001 当前状态是什么？",
        "REALTIME_BUSINESS",
        91001,
        "DRAFT",
    ),
    QueryCase(
        "realtime-91002",
        "realtime",
        "请查询采购申请 91002 现在到哪一步了？",
        "REALTIME_BUSINESS",
        91002,
        "PENDING_REVIEW",
    ),
    QueryCase(
        "realtime-91003",
        "realtime",
        "帮我查采购申请 91003 的实时状态。",
        "REALTIME_BUSINESS",
        91003,
        "REJECTED",
    ),
    QueryCase(
        "realtime-91004",
        "realtime",
        "采购申请 91004 当前由哪个环节处理？",
        "REALTIME_BUSINESS",
        91004,
        "PENDING_PURCHASE",
    ),
    QueryCase(
        "realtime-91005",
        "realtime",
        "请查询采购申请 91005 的当前办理进度。",
        "REALTIME_BUSINESS",
        91005,
        "PURCHASING",
    ),
    QueryCase(
        "realtime-91006",
        "realtime",
        "查一下采购申请 91006 目前的状态。",
        "REALTIME_BUSINESS",
        91006,
        "PENDING_WAREHOUSE",
    ),
    QueryCase(
        "realtime-91007",
        "realtime",
        "采购申请 91007 是否已经办完？",
        "REALTIME_BUSINESS",
        91007,
        "COMPLETED",
    ),
    QueryCase(
        "realtime-91008",
        "realtime",
        "请确认采购申请 91008 当前状态。",
        "REALTIME_BUSINESS",
        91008,
        "COMPLETED",
    ),
    QueryCase(
        "realtime-91009",
        "realtime",
        "采购申请 91009 现在处于哪个环节？",
        "REALTIME_BUSINESS",
        91009,
        "COMPLETED",
    ),
    QueryCase(
        "realtime-91003-handler",
        "realtime",
        "采购申请 91003 当前处理人是谁？",
        "REALTIME_BUSINESS",
        91003,
        "REJECTED",
    ),
    QueryCase(
        "hybrid-91001",
        "hybrid",
        "采购申请 91001 当前状态是什么，草稿应该如何提交？",
        "HYBRID",
        91001,
        "DRAFT",
        True,
    ),
    QueryCase(
        "hybrid-91002",
        "hybrid",
        "采购申请 91002 当前到哪一步，楼长审核有哪些规定？",
        "HYBRID",
        91002,
        "PENDING_REVIEW",
        True,
    ),
    QueryCase(
        "hybrid-91003",
        "hybrid",
        "采购申请 91003 当前被驳回了吗？被驳回后应该怎么办？",
        "HYBRID",
        91003,
        "REJECTED",
        True,
    ),
    QueryCase(
        "hybrid-91004",
        "hybrid",
        "采购申请 91004 当前状态是什么，通过审核后的流程是什么？",
        "HYBRID",
        91004,
        "PENDING_PURCHASE",
        True,
    ),
    QueryCase(
        "hybrid-91005",
        "hybrid",
        "采购申请 91005 当前进度如何，采购登记应填写哪些内容？",
        "HYBRID",
        91005,
        "PURCHASING",
        True,
    ),
    QueryCase(
        "hybrid-91006",
        "hybrid",
        "采购申请 91006 当前状态是什么，入库办理有什么规定？",
        "HYBRID",
        91006,
        "PENDING_WAREHOUSE",
        True,
    ),
    QueryCase(
        "hybrid-91007",
        "hybrid",
        "采购申请 91007 当前是否完成，完成后的记录能否修改？",
        "HYBRID",
        91007,
        "COMPLETED",
        True,
    ),
    QueryCase(
        "hybrid-91008",
        "hybrid",
        "采购申请 91008 当前状态是什么，入库数量不一致应如何处理？",
        "HYBRID",
        91008,
        "COMPLETED",
        True,
    ),
    QueryCase(
        "hybrid-91009",
        "hybrid",
        "采购申请 91009 当前到哪一步，采购完成流程如何确认？",
        "HYBRID",
        91009,
        "COMPLETED",
        True,
    ),
    QueryCase(
        "hybrid-91002-fields",
        "hybrid",
        "采购申请 91002 当前状态是什么，楼长通过前的字段填写规定是什么？",
        "HYBRID",
        91002,
        "PENDING_REVIEW",
        True,
    ),
)

CACHE_CASES = (
    next(case for case in CASES if case.case_id == "knowledge-rejection-rule"),
    next(case for case in CASES if case.case_id == "hybrid-91003"),
)

WARMUP_CASE = QueryCase(
    "warmup-knowledge",
    "warmup",
    "采购申请被楼长驳回后应该怎么办？",
    "KNOWLEDGE",
    requires_knowledge=True,
)


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 2)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
    return round(value, 2)


def signed_headers(settings: AgentSettings, method: str, path: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    platform_type = "TEST_PLATFORM"
    platform_user_id = "test-user-01"
    return {
        "X-Platform-Type": platform_type,
        "X-Platform-User-Id": platform_user_id,
        "X-Gateway-Timestamp": timestamp,
        "X-Gateway-Nonce": nonce,
        "X-Gateway-Signature": build_gateway_signature(
            secret=settings.identity_gateway_secret,
            method=method,
            path=path,
            platform_type=platform_type,
            platform_user_id=platform_user_id,
            timestamp=timestamp,
            nonce=nonce,
        ),
    }


async def complete_conversation(
    client: httpx.AsyncClient,
    settings: AgentSettings,
    conversation_id: int,
) -> None:
    path = f"/api/v1/agent/conversations/{conversation_id}/complete"
    response = await client.post(
        path,
        headers=signed_headers(settings, "POST", path),
        json={},
    )
    response.raise_for_status()


def trace_metrics(data: dict[str, Any]) -> dict[str, float]:
    metrics = {
        "rewrite_ms": 0.0,
        "embedding_ms": 0.0,
        "retrieval_ms": 0.0,
        "rerank_ms": 0.0,
        "parent_db_ms": 0.0,
        "context_ms": 0.0,
        "rag_total_ms": 0.0,
        "rag_local_ms": 0.0,
        "compose_ms": 0.0,
        "compose_provider_ttft_ms": 0.0,
        "llm_full_ms": 0.0,
        "llm_ttft_ms": 0.0,
        "graph_e2e_ms": float((data.get("performance") or {}).get("graph_total_ms") or 0),
    }
    llm_full: list[float] = []
    llm_ttft: list[float] = []
    execution = data.get("execution") or {}
    for event in execution.get("trace_events") or []:
        result = event.get("result") or {}
        if event.get("name") == "knowledge_retrieval":
            timings = result.get("rag_timings") or {}
            metrics["rewrite_ms"] = float(timings.get("rewrite_ms") or 0)
            metrics["embedding_ms"] = float(timings.get("embedding_ms") or 0)
            metrics["retrieval_ms"] = float(timings.get("retrieval_wall_ms") or 0)
            metrics["rerank_ms"] = float(timings.get("rerank_ms") or 0)
            metrics["parent_db_ms"] = float(timings.get("parent_db_ms") or 0)
            metrics["context_ms"] = float(timings.get("context_build_ms") or 0)
            metrics["rag_total_ms"] = float(timings.get("total_ms") or 0)
            metrics["rag_local_ms"] = sum(
                float(timings.get(name) or 0)
                for name in (
                    "knowledge_version_ms",
                    "embedding_ms",
                    "filter_build_ms",
                    "retrieval_wall_ms",
                    "candidate_conversion_ms",
                    "rerank_ms",
                    "parent_db_ms",
                    "context_build_ms",
                )
            )
        if event.get("name") == "compose_answer":
            metrics["compose_ms"] = float(result.get("latency_ms") or event.get("duration_ms") or 0)
            metrics["compose_provider_ttft_ms"] = float(result.get("first_token_ms") or 0)
        if result.get("model_used") is True:
            if result.get("latency_ms") is not None:
                llm_full.append(float(result["latency_ms"]))
            if result.get("first_token_ms") is not None:
                llm_ttft.append(float(result["first_token_ms"]))
    metrics["llm_full_ms"] = sum(llm_full)
    metrics["llm_ttft_ms"] = sum(llm_ttft)
    return metrics


def cache_metrics(data: dict[str, Any]) -> dict[str, bool]:
    trace = (data.get("knowledge") or {}).get("trace") or {}
    return {
        "rewrite_cache_hit": bool(trace.get("rewrite_cache_hit")),
        "embedding_cache_hit": bool(trace.get("embedding_cache_hit")),
        "retrieval_cache_hit": bool(trace.get("retrieval_cache_hit")),
        "rewrite_skipped": bool(trace.get("rewrite_skipped")),
    }


def validate_quality(case: QueryCase, data: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if data.get("route") != case.expected_route:
        failures.append(f"route={data.get('route')} expected={case.expected_route}")
    execution = data.get("execution") or {}
    errors = execution.get("errors") or []
    if errors:
        failures.append(f"graph_errors={len(errors)}")
    tools = execution.get("tools") or []
    tool_calls = [item for item in tools if item.get("name") == "get_purchase_request"]
    if case.requirement_id is not None:
        matches = [
            item
            for item in tool_calls
            if item.get("success") is True
            and (item.get("arguments") or {}).get("requirement_id") == case.requirement_id
            and (item.get("data") or {}).get("status") == case.expected_status
        ]
        if not matches:
            failures.append(f"tool_result_missing={case.requirement_id}/{case.expected_status}")
    knowledge = data.get("knowledge") or {}
    citations = knowledge.get("citations") or []
    parent_ids = {str(item.get("parent_id")) for item in citations}
    section_text = " ".join(
        " ".join(str(part) for part in item.get("section_path") or []) for item in citations
    )
    if case.requires_knowledge:
        if case.expect_answerable:
            if not data.get("evidence_sufficient") or not citations:
                failures.append("knowledge_evidence_missing")
            if case.relevant_parent_ids and not parent_ids.intersection(case.relevant_parent_ids):
                failures.append("relevant_parent_not_retrieved")
            if case.expected_section_terms and not any(
                term in section_text for term in case.expected_section_terms
            ):
                failures.append("expected_section_not_cited")
        elif data.get("evidence_sufficient") or citations:
            failures.append("negative_query_did_not_abstain")
    compose_events = [
        event
        for event in execution.get("trace_events") or []
        if event.get("name") == "compose_answer"
    ]
    if compose_events and compose_events[-1].get("status") not in {"SUCCESS", "SKIPPED"}:
        failures.append(f"compose_status={compose_events[-1].get('status')}")
    return {
        "passed": not failures,
        "failures": failures,
        "citation_count": len(citations),
        "parent_ids": sorted(parent_ids),
        "tool_success": not case.requirement_id
        or not any(failure.startswith("tool_result_missing") for failure in failures),
    }


async def sample(
    agent_client: httpx.AsyncClient,
    backend_client: httpx.AsyncClient,
    settings: AgentSettings,
    case: QueryCase,
    run_number: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    current_event: str | None = None
    first_status_ms: float | None = None
    first_body_ms: float | None = None
    completed: dict[str, Any] | None = None
    payload = {
        "platform_type": "TEST_PLATFORM",
        "platform_user_id": "test-user-01",
        "message": case.query,
        "external_conversation_id": f"PERF-{case.scenario}-{run_number}-{uuid4().hex}",
        "external_message_id": f"perf-{uuid4().hex}",
    }
    async with agent_client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers={"X-Request-Id": f"perf-{uuid4().hex}"},
        json=payload,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current_event = line[7:]
                if first_status_ms is None:
                    first_status_ms = elapsed_ms(started)
            elif line.startswith("data: "):
                event_data = json.loads(line[6:])
                if current_event == "answer_delta" and first_body_ms is None:
                    first_body_ms = elapsed_ms(started)
                if current_event == "completed":
                    completed = event_data
    e2e_ms = elapsed_ms(started)
    if completed is None:
        raise RuntimeError(f"{case.case_id} did not emit completed")
    data = completed.get("data") or {}
    quality = validate_quality(case, data)
    conversation_id = int(data["conversation_id"])
    await complete_conversation(backend_client, settings, conversation_id)
    if not quality["passed"]:
        raise RuntimeError(f"{case.case_id} quality failure: {quality['failures']}")
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "run": run_number,
        "route": data.get("route"),
        "status_feedback_ms": first_status_ms,
        "ttft_ms": first_body_ms,
        "e2e_ms": e2e_ms,
        **trace_metrics(data),
        **cache_metrics(data),
        "quality": quality,
        "performance": data.get("performance") or {},
    }


async def sample_with_retries(
    agent_client: httpx.AsyncClient,
    backend_client: httpx.AsyncClient,
    settings: AgentSettings,
    case: QueryCase,
    run_number: int,
    *,
    max_attempts: int = 3,
) -> tuple[dict[str, Any], int]:
    failures: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            row = await sample(agent_client, backend_client, settings, case, run_number)
            return row, attempt - 1
        except (httpx.HTTPError, RuntimeError) as exc:
            failures.append(str(exc))
            if attempt < max_attempts:
                await asyncio.sleep(5)
    raise RuntimeError(
        f"{case.case_id} failed after {max_attempts} attempts: {' | '.join(failures)}"
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    metric_names = (
        "status_feedback_ms",
        "ttft_ms",
        "e2e_ms",
        "rewrite_ms",
        "embedding_ms",
        "retrieval_ms",
        "rerank_ms",
        "parent_db_ms",
        "context_ms",
        "rag_total_ms",
        "rag_local_ms",
        "compose_ms",
        "compose_provider_ttft_ms",
        "llm_full_ms",
        "llm_ttft_ms",
        "graph_e2e_ms",
    )
    for scenario in ("knowledge", "realtime", "hybrid"):
        selected = [row for row in rows if row["scenario"] == scenario]
        if not selected:
            continue
        summary[scenario] = {}
        for metric in metric_names:
            values = [float(row[metric]) for row in selected if row.get(metric) is not None]
            summary[scenario][metric] = {
                "p50": percentile(values, 0.5),
                "p95": percentile(values, 0.95),
            }
    return summary


def selected_cases(profile: str) -> tuple[QueryCase, ...]:
    return CASES if profile == "uncached-unique" else CACHE_CASES


def validate_case_routes(cases: tuple[QueryCase, ...]) -> None:
    router = FirstVersionRouter()
    invalid = [
        case.case_id
        for case in cases
        if router.classify(case.query).value != case.expected_route
        or router.should_use_model(case.query)
    ]
    if invalid:
        raise ValueError(f"benchmark cases require model Router or mismatch: {invalid}")


async def run_mode(mode: str, samples: int, profile: str) -> dict[str, Any]:
    optimized = mode == "optimized"
    settings = AgentSettings(
        performance_optimizations_enabled=optimized,
        procurement_backend_timeout_seconds=60,
        task_timeout_seconds=300,
    )
    application = create_agent_app(settings=settings)
    rows: list[dict[str, Any]] = []
    discarded_attempts = 0
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://agent.local",
                timeout=360,
            ) as agent,
            httpx.AsyncClient(
                base_url=settings.procurement_backend_url,
                timeout=settings.procurement_backend_timeout_seconds,
            ) as backend,
        ):
            _, discarded = await sample_with_retries(agent, backend, settings, WARMUP_CASE, 0)
            discarded_attempts += discarded
            for case in selected_cases(profile):
                repetitions = 1 if profile == "uncached-unique" else samples
                if profile == "cache-hit":
                    _, discarded = await sample_with_retries(agent, backend, settings, case, 0)
                    discarded_attempts += discarded
                for run_number in range(1, repetitions + 1):
                    row, discarded = await sample_with_retries(
                        agent, backend, settings, case, run_number
                    )
                    discarded_attempts += discarded
                    rows.append(row)
                    print(json.dumps({"mode": mode, **row}, ensure_ascii=False), flush=True)
    return {
        "mode": mode,
        "profile": profile,
        "discarded_attempts": discarded_attempts,
        "summary": summarize(rows),
        "rows": rows,
    }


async def run_remote_mode(
    mode: str,
    samples: int,
    base_url: str,
    profile: str,
) -> dict[str, Any]:
    settings = AgentSettings(procurement_backend_timeout_seconds=60)
    rows: list[dict[str, Any]] = []
    discarded_attempts = 0
    async with (
        httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=360) as agent,
        httpx.AsyncClient(
            base_url=settings.procurement_backend_url,
            timeout=60,
        ) as backend,
    ):
        _, discarded = await sample_with_retries(agent, backend, settings, WARMUP_CASE, 0)
        discarded_attempts += discarded
        for case in selected_cases(profile):
            repetitions = 1 if profile == "uncached-unique" else samples
            if profile == "cache-hit":
                _, discarded = await sample_with_retries(agent, backend, settings, case, 0)
                discarded_attempts += discarded
            for run_number in range(1, repetitions + 1):
                row, discarded = await sample_with_retries(
                    agent, backend, settings, case, run_number
                )
                discarded_attempts += discarded
                rows.append(row)
                print(json.dumps({"mode": mode, **row}, ensure_ascii=False), flush=True)
    return {
        "mode": mode,
        "profile": profile,
        "discarded_attempts": discarded_attempts,
        "summary": summarize(rows),
        "rows": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--mode", choices=["baseline", "optimized", "both"], default="both")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--profile",
        choices=["uncached-unique", "cache-hit"],
        default="uncached-unique",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "performance" / "agent-latency-comparison.json",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_case_routes(selected_cases(args.profile))
    if args.base_url:
        if args.mode == "both":
            raise ValueError("--base-url requires a single --mode")
        return {
            "results": [await run_remote_mode(args.mode, args.samples, args.base_url, args.profile)]
        }
    modes = ["baseline", "optimized"] if args.mode == "both" else [args.mode]
    results = [await run_mode(mode, args.samples, args.profile) for mode in modes]
    return {"results": results}


def main() -> int:
    args = parse_args()
    payload = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
