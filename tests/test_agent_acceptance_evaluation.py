from pathlib import Path

from agent_app.evaluation.acceptance import (
    AgentAcceptanceResult,
    load_agent_acceptance_cases,
    percentile,
    summarize_agent_acceptance,
)
from agent_app.evaluation.rag import load_rag_evaluation_cases

ROOT = Path(__file__).resolve().parents[1]


def result(case_id: str, category: str, *, success: bool, duration: int):
    return AgentAcceptanceResult(
        case_id=case_id,
        category=category,
        question="test",
        expected_route="KNOWLEDGE",
        actual_route="KNOWLEDGE",
        route_correct=True,
        tool_correct=True,
        success=success,
        model_call_count=2,
        successful_model_call_count=1,
        tool_call_count=1,
        duration_ms=duration,
    )


def test_percentile_interpolates() -> None:
    assert percentile([100, 200, 300, 400], 0.5) == 250
    assert percentile([100, 200, 300, 400], 0.95) == 385


def test_summary_includes_global_and_category_metrics() -> None:
    summary = summarize_agent_acceptance(
        [
            result("a", "KNOWLEDGE", success=True, duration=100),
            result("b", "KNOWLEDGE", success=False, duration=300),
        ]
    )
    assert summary["total_cases"] == 2
    assert summary["task_success_rate"] == 0.5
    assert summary["route_accuracy"] == 1.0
    assert summary["tool_accuracy"] is None
    assert summary["average_duration_ms"] == 200
    assert summary["categories"]["KNOWLEDGE"]["average_model_call_count"] == 2
    assert summary["average_successful_model_call_count"] == 1
    assert summary["model_cost_available"] is False
    assert summary["model_cost_reported_cases"] == 0
    assert summary["failed_cases"][0]["case_id"] == "b"


def test_fixed_acceptance_fixtures_have_expected_sizes() -> None:
    agent_cases = load_agent_acceptance_cases(
        ROOT / "tests" / "fixtures" / "agent_acceptance_evaluation_v0.1.json"
    )
    assert len(agent_cases) == 25
    assert {
        category: sum(case.category == category for case in agent_cases)
        for category in {case.category for case in agent_cases}
    } == {
        "KNOWLEDGE": 5,
        "REALTIME_BUSINESS": 5,
        "COMPLEX_QUERY": 5,
        "RISK_INVESTIGATION": 5,
        "FORM_PREFILL": 5,
    }
    assert (
        len(
            load_rag_evaluation_cases(
                ROOT / "tests" / "fixtures" / "rag_acceptance_evaluation_v0.1.json"
            )
        )
        == 10
    )
