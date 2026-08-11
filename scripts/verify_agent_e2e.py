"""Run the three minimum business scenarios through the formal Agent HTTP API."""

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    message: str
    expected_route: str
    requires_rag: bool
    requires_tool: bool


SCENARIOS = (
    Scenario(
        name="knowledge",
        message="采购申请被楼长驳回后应该怎么办？",
        expected_route="KNOWLEDGE",
        requires_rag=True,
        requires_tool=False,
    ),
    Scenario(
        name="realtime",
        message="帮我查一下测试采购单 91003 现在到哪个环节了？",
        expected_route="REALTIME_BUSINESS",
        requires_rag=False,
        requires_tool=True,
    ),
    Scenario(
        name="hybrid",
        message="这张采购单现在被驳回了，我接下来应该怎么处理？",
        expected_route="HYBRID",
        requires_rag=True,
        requires_tool=True,
    ),
)


def model_trace(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for event in trace_events:
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if event.get("name") not in {"model_router", "compose_answer", "review"}:
            continue
        selected.append(
            {
                "name": event.get("name"),
                "status": event.get("status"),
                "model_used": result.get("model_used"),
                "primary_model": result.get("primary_model"),
                "actual_model": result.get("actual_model"),
                "fallback_used": result.get("fallback_used"),
                "fallback_reason": result.get("fallback_reason"),
            }
        )
    return selected


def summarize(scenario: Scenario, body: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    execution = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    events = (
        execution.get("trace_events") if isinstance(execution.get("trace_events"), list) else []
    )
    tools = execution.get("tools") if isinstance(execution.get("tools"), list) else []
    knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else None
    citations = knowledge.get("citations", []) if knowledge else []
    retrieval_trace = knowledge.get("trace", {}) if knowledge else {}
    tool_calls = [item for item in tools if item.get("name") == "get_purchase_request"]
    successful_tool_calls = [item for item in tool_calls if item.get("success") is True]
    model_events = model_trace(events)
    model_used = any(item["model_used"] is True for item in model_events)
    route_ok = data.get("route") == scenario.expected_route
    rag_ok = bool(citations) if scenario.requires_rag else knowledge is None
    tool_ok = bool(successful_tool_calls) if scenario.requires_tool else not tool_calls
    realtime_status_ok = True
    if scenario.requires_tool:
        realtime_status_ok = any(
            isinstance(item.get("data"), dict) and item["data"].get("status") == "REJECTED"
            for item in successful_tool_calls
        )
    passed = (
        body.get("success") is True
        and route_ok
        and rag_ok
        and tool_ok
        and realtime_status_ok
        and model_used
    )
    return passed, {
        "request": {
            "message": scenario.message,
            "expected_route": scenario.expected_route,
        },
        "response": {
            "trace_id": body.get("trace_id"),
            "conversation_id": data.get("conversation_id"),
            "route": data.get("route"),
            "restored_from_snapshot": data.get("restored_from_snapshot"),
            "reply": data.get("reply"),
            "evidence_sufficient": data.get("evidence_sufficient"),
            "errors": execution.get("errors", []),
        },
        "rag": {
            "used": knowledge is not None,
            "original_query": retrieval_trace.get("original_query"),
            "rewritten_query": retrieval_trace.get("rewritten_query"),
            "rewrite_applied": retrieval_trace.get("rewrite_applied"),
            "evidence_ids": retrieval_trace.get("final_evidence_ids", []),
            "citations": [
                {
                    "citation_id": item.get("citation_id"),
                    "document_id": item.get("document_id"),
                    "document_title": item.get("document_title"),
                    "section_path": item.get("section_path"),
                    "source_path": item.get("source_path"),
                    "source_start_line": item.get("source_start_line"),
                    "source_end_line": item.get("source_end_line"),
                }
                for item in citations
            ],
        },
        "tool": [
            {
                "name": item.get("name"),
                "arguments": item.get("arguments"),
                "success": item.get("success"),
                "code": item.get("code"),
                "source": item.get("source"),
                "data": item.get("data"),
            }
            for item in tool_calls
        ],
        "graph_path": [{"name": item.get("name"), "status": item.get("status")} for item in events],
        "model_trace": model_events,
    }


async def verify(
    base_url: str,
    external_conversation_id: str,
    request_timeout_seconds: float,
    only: str,
) -> int:
    results: list[tuple[Scenario, bool, dict[str, Any]]] = []
    selected = (
        SCENARIOS
        if only == "all"
        else tuple(scenario for scenario in SCENARIOS if scenario.name == only)
    )
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), timeout=request_timeout_seconds
    ) as client:
        for scenario in selected:
            response = await client.post(
                "/api/v1/chat",
                headers={"X-Request-Id": f"e2e-{scenario.name}-{uuid4().hex[:12]}"},
                json={
                    "platform_type": "TEST_PLATFORM",
                    "platform_user_id": "test-user-01",
                    "message": scenario.message,
                    "external_conversation_id": external_conversation_id,
                    "external_message_id": f"{external_conversation_id}-{scenario.name}",
                },
            )
            if response.is_error:
                print(
                    f"[FAIL] {scenario.name} | HTTP {response.status_code} | "
                    f"{response.text[:1000]}",
                    flush=True,
                )
                return 1
            body = response.json()
            passed, detail = summarize(scenario, body)
            results.append((scenario, passed, detail))
            print(
                f"[{'PASS' if passed else 'FAIL'}] {scenario.name} | "
                f"{json.dumps(detail, ensure_ascii=False, default=str)}",
                flush=True,
            )

    conversation_ids = {detail["response"]["conversation_id"] for _, _, detail in results}
    if only != "all":
        return 0 if all(passed for _, passed, _ in results) else 1
    conversation_ok = len(conversation_ids) == 1 and None not in conversation_ids
    hybrid_detail = next(detail for scenario, _, detail in results if scenario.name == "hybrid")
    state_reused = any(
        item.get("arguments", {}).get("requirement_id") == 91003 for item in hybrid_detail["tool"]
    )
    print(
        f"[{'PASS' if conversation_ok and state_reused else 'FAIL'}] session | "
        f"conversation_ids={sorted(conversation_ids, key=str)}; "
        f"follow_up_requirement_id_restored={state_reused}",
        flush=True,
    )
    return 0 if all(passed for _, passed, _ in results) and conversation_ok and state_reused else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument(
        "--external-conversation-id",
        default=f"E2E-MINIMAL-{uuid4().hex}",
    )
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--only",
        choices=["all", "knowledge", "realtime", "hybrid"],
        default="all",
    )
    args = parser.parse_args()
    return asyncio.run(
        verify(
            args.base_url,
            args.external_conversation_id,
            args.timeout,
            args.only,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
