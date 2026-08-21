from pathlib import Path

from agent_app.evaluation.acceptance import (
    AgentAcceptanceResult,
    ResultAssertion,
    evaluate_result_assertion,
    load_agent_acceptance_cases,
    percentile,
    summarize_agent_acceptance,
)
from agent_app.evaluation.rag import load_rag_evaluation_cases

ROOT = Path(__file__).resolve().parents[1]


def result(
    case_id: str,
    category: str,
    *,
    success: bool,
    result_correct: bool,
    duration: int,
    expected_tools: list[str] | None = None,
    actual_tools: list[str] | None = None,
    tool_evaluated: bool = False,
    tool_correct: bool = True,
) -> AgentAcceptanceResult:
    return AgentAcceptanceResult(
        case_id=case_id,
        category=category,
        question="test",
        expected_route=category,
        expected_tools=expected_tools or [],
        actual_route=category,
        route_correct=True,
        actual_tools=actual_tools or [],
        tool_skill_evaluated=tool_evaluated,
        tool_correct=tool_correct,
        result_correct=result_correct,
        execution_complete=True,
        success=success,
        model_call_count=2,
        successful_model_call_count=1,
        tool_call_count=len(actual_tools or []),
        duration_ms=duration,
    )


def test_percentile_interpolates() -> None:
    assert percentile([100, 200, 300, 400], 0.5) == 250
    assert percentile([100, 200, 300, 400], 0.95) == 385


def test_summary_task_success_and_result_denominators_use_all_cases() -> None:
    summary = summarize_agent_acceptance(
        [
            result("a", "KNOWLEDGE", success=True, result_correct=True, duration=100),
            result("b", "KNOWLEDGE", success=False, result_correct=False, duration=300),
        ]
    )

    assert summary["total_cases"] == 2
    assert summary["task_success_rate"] == 0.5
    assert summary["result_correctness_rate"] == 0.5
    assert summary["route_accuracy"] == 1.0
    assert summary["average_duration_ms"] == 200
    assert summary["p50_duration_ms"] == 200
    assert summary["categories"]["KNOWLEDGE"]["task_success_rate"] == 0.5
    assert summary["failed_cases"][0]["case_id"] == "b"


def test_tool_accuracy_denominator_only_includes_tool_or_skill_cases() -> None:
    summary = summarize_agent_acceptance(
        [
            result("no-tool", "KNOWLEDGE", success=True, result_correct=True, duration=10),
            result(
                "tool-ok",
                "REALTIME_BUSINESS",
                success=True,
                result_correct=True,
                duration=20,
                expected_tools=["get_purchase_request"],
                actual_tools=["get_purchase_request"],
                tool_evaluated=True,
            ),
            result(
                "tool-bad",
                "REALTIME_BUSINESS",
                success=False,
                result_correct=True,
                duration=30,
                expected_tools=["get_purchase_request", "get_requirement_timeline"],
                actual_tools=["get_purchase_request"],
                tool_evaluated=True,
                tool_correct=False,
            ),
        ]
    )

    assert summary["tool_evaluated_cases"] == 2
    assert summary["tool_skill_accuracy"] == 0.5
    assert summary["categories"]["KNOWLEDGE"]["tool_skill_accuracy"] is None


def test_form_result_assertion_checks_fields_and_missing_values() -> None:
    assertion = ResultAssertion(
        kind="FORM_PREFILL",
        classification_status="AMBIGUOUS",
        candidate_professions=["10kV开关柜", "400V配电柜"],
        expected_fields={"quantity": 1},
        missing_fields_contains=["device_profession"],
    )
    passed, failures, snapshot = evaluate_result_assertion(
        assertion,
        {
            "reply": "请确认配电柜类型",
            "form_draft": {"quantity": 1},
            "form_classification": {
                "classification_status": "AMBIGUOUS",
                "candidate_professions": ["10kV开关柜", "400V配电柜"],
            },
            "form_missing_fields": ["device_profession"],
        },
    )

    assert passed is True
    assert failures == []
    assert snapshot["form_draft"]["quantity"] == 1


def test_complex_result_assertion_uses_backend_ground_truth() -> None:
    assertion = ResultAssertion(kind="COMPLEX_QUERY")
    passed, failures, _ = evaluate_result_assertion(
        assertion,
        {"reply": "共10条", "analysis": {"summary": {"count": 10}, "groups": []}},
        ground_truth={"summary": {"count": 11}, "groups": []},
    )

    assert passed is False
    assert failures == ["analysis.summary differs from backend ground truth"]


def test_knowledge_assertion_uses_public_chat_sources_and_evidence_count() -> None:
    assertion = ResultAssertion(kind="KNOWLEDGE", min_evidence_count=1, min_citation_count=1)
    passed, failures, snapshot = evaluate_result_assertion(
        assertion,
        {
            "reply": "按制度应重新提交。",
            "knowledge": None,
            "knowledge_sources": [{"title": "采购制度", "section_path": ["驳回"]}],
            "evidence_count": 3,
        },
    )

    assert passed is True
    assert failures == []
    assert snapshot["answerable"] is True
    assert snapshot["citation_count"] == 1
    assert snapshot["evidence_count"] == 3


def test_business_assertion_accepts_localized_status_from_reply() -> None:
    assertion = ResultAssertion(kind="REALTIME_BUSINESS", ground_truth_fields=["status"])
    passed, failures, _ = evaluate_result_assertion(
        assertion,
        {"reply": "当前状态：已完成", "business_results": []},
        ground_truth={"values": {"status": "COMPLETED"}, "required_values": ["status"]},
    )

    assert passed is True
    assert failures == []


def test_fixed_v02_fixtures_have_representative_sizes() -> None:
    agent_cases = load_agent_acceptance_cases(
        ROOT / "tests" / "fixtures" / "agent_acceptance_evaluation_v0.2.json"
    )
    rag_cases = load_rag_evaluation_cases(
        ROOT / "tests" / "fixtures" / "rag_acceptance_evaluation_v0.2.json"
    )

    counts = {
        category: sum(case.category == category for case in agent_cases)
        for category in {case.category for case in agent_cases}
    }
    assert len(agent_cases) == 78
    assert counts == {
        "KNOWLEDGE": 12,
        "REALTIME_BUSINESS": 12,
        "COMPLEX_QUERY": 12,
        "RISK_INVESTIGATION": 12,
        "FORM_PREFILL": 12,
        "RECOMMENDATION": 12,
        "HYBRID": 6,
    }
    assert 12 <= sum(case.boundary for case in agent_cases) <= 16
    assert len(rag_cases) == 38
