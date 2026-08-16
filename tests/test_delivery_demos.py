from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from agent_app.evaluation.delivery import DeliveryDemoRunner


def execution(trace_id: str, route: str, status: str = "COMPLETE") -> dict:
    return {
        "trace_id": trace_id,
        "route": route,
        "status": status,
        "duration_ms": 10,
        "step_count": 1,
        "tool_call_count": 1,
        "evidence_count": 1,
        "restored_from_snapshot": False,
        "components": [],
        "model_usage": {"configured": False, "call_count": 0},
        "trace_events": [],
        "tools": [],
        "errors": [],
    }


def analysis_data(*, follow_up: bool) -> dict:
    query = {
        "created_from": "2026-08-01",
        "created_to": "2026-08-05",
        "device_professions": ["服务器"],
        "group_by": "BRAND",
        "aggregations": [
            "COUNT",
            "AVERAGE_UNIT_PRICE",
            "MEDIAN_UNIT_PRICE",
            "TOTAL_AMOUNT",
        ],
        "exclude_delayed_suppliers": follow_up,
    }
    return {
        "answer": "完成分析",
        "plan": {
            "goal": "统计采购",
            "steps": [
                {
                    "step_id": "purchase_query",
                    "objective": "查询",
                    "tool": "query_purchase_analytics",
                    "arguments": {"query": query},
                }
            ],
            "termination_condition": "查询完成",
            "query_context": query,
        },
        "effective_query": query,
        "summary": {
            "count": 9,
            "average_unit_price": "1112.50",
            "median_unit_price": "950.00",
            "total_amount": "34350.00",
        },
        "groups": [{"key": "TEST-BRAND", "count": 9}],
        "step_results": [],
        "partial_success": False,
    }


def chat_envelope(data: dict, trace_id: str) -> dict:
    return {
        "success": True,
        "code": "OK",
        "message": "回答已生成",
        "trace_id": trace_id,
        "data": data,
    }


def analysis_chat(*, follow_up: bool) -> dict:
    trace_id = f"trace-analysis-{int(follow_up)}"
    return chat_envelope(
        {
            "task_id": str(uuid4()),
            "conversation_id": 100,
            "reply": "完成分析",
            "route": "COMPLEX_QUERY",
            "restored_from_snapshot": follow_up,
            "tool_call_count": 1,
            "evidence_count": 1,
            "execution": execution(trace_id, "COMPLEX_QUERY"),
            "analysis": analysis_data(follow_up=follow_up),
        },
        trace_id,
    )


def risk_chat() -> dict:
    trace_id = "trace-risk"
    return chat_envelope(
        {
            "task_id": str(uuid4()),
            "conversation_id": 200,
            "reply": "风险调查结果不替代人工审批结论。",
            "route": "RISK_INVESTIGATION",
            "restored_from_snapshot": False,
            "tool_call_count": 4,
            "evidence_count": 2,
            "execution": execution(trace_id, "RISK_INVESTIGATION", "PARTIAL"),
            "risk_investigation": {
                "requirement_id": 91009,
                "answer": "风险调查结果不替代人工审批结论。",
                "summary_items": [
                    {
                        "risk_code": "PRICE_DEVIATION",
                        "risk_type": "价格异常",
                        "risk_level": "MEDIUM",
                        "backend_rule_matched": True,
                        "facts": {},
                        "metrics": {},
                        "related_record_ids": [91009],
                        "data_sources": ["/api/v1/requirements/91009/risk-signals"],
                        "applicable_rule": {},
                        "possible_causes": ["待核实"],
                        "information_complete": False,
                        "information_gaps": ["缺少真实制度"],
                        "human_checks": ["核对询价依据"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "risk_signals",
                        "kind": "RISK_SIGNALS",
                        "status": "SUCCESS",
                        "source": "/api/v1/requirements/91009/risk-signals",
                        "trace_id": trace_id,
                    },
                    {
                        "evidence_id": "knowledge_rule",
                        "kind": "KNOWLEDGE_RULE",
                        "status": "UNAVAILABLE",
                        "source": "rag://procurement-rules",
                    },
                ],
                "review": {"passed": True, "checked_items": 1},
                "complete": False,
                "knowledge_evidence_available": False,
                "warnings": ["真实采购制度材料尚未提供"],
            },
        },
        trace_id,
    )


@pytest.mark.asyncio
async def test_delivery_demos_pass_two_scenarios_and_block_real_knowledge() -> None:
    responses = [analysis_chat(follow_up=False), analysis_chat(follow_up=True), risk_chat()]

    async def handler(request: Request) -> Response:
        assert request.url.path == "/demo-api/agent-chat"
        payload = json.loads(request.content)
        assert payload["platform_user_id"] == "test-user-05"
        return Response(200, json=responses.pop(0))

    async with AsyncClient(
        transport=MockTransport(handler),
        base_url="http://backend.test",
    ) as client:
        report = await DeliveryDemoRunner(client).run()

    assert report.total == 3
    assert report.passed == 2
    assert report.failed == 0
    assert report.blocked == 1
    assert [item.status for item in report.results] == ["PASSED", "PASSED", "BLOCKED"]


@pytest.mark.asyncio
async def test_delivery_demo_reports_http_failure_without_hiding_knowledge_gate() -> None:
    async def handler(_request: Request) -> Response:
        return Response(503, json={"code": "SERVICE_UNAVAILABLE"})

    async with AsyncClient(
        transport=MockTransport(handler),
        base_url="http://backend.test",
    ) as client:
        report = await DeliveryDemoRunner(client).run()

    assert report.failed == 2
    assert report.blocked == 1
    assert all(item.reason for item in report.results if item.status == "FAILED")
