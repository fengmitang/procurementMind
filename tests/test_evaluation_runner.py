import pytest

from agent_app.evaluation.runner import EvaluationRunner
from agent_app.evaluation.schemas import EvaluationCase


class Subject:
    async def execute(self, payload: dict) -> dict:
        if payload.get("fail"):
            raise RuntimeError("failed")
        return {"plan": {"tool": "query", "count": payload["count"]}, "extra": True}


@pytest.mark.asyncio
async def test_evaluation_runner_reports_subset_mismatch_and_error() -> None:
    cases = [
        EvaluationCase(
            case_id="pass",
            category="planner",
            input={"count": 9},
            expected_subset={"plan": {"tool": "query", "count": 9}},
        ),
        EvaluationCase(
            case_id="mismatch",
            category="planner",
            input={"count": 8},
            expected_subset={"plan": {"count": 9}},
        ),
        EvaluationCase(
            case_id="error",
            category="fault",
            input={"fail": True},
            expected_subset={},
        ),
    ]

    report = await EvaluationRunner().run("test-suite", cases, Subject())

    assert report.total == 3
    assert report.passed == 1
    assert report.failed == 2
    assert report.pass_rate == pytest.approx(1 / 3)
    assert report.results[1].mismatches == ["plan.count: expected=9, actual=8"]
    assert report.results[2].error_code == "EVALUATION_SUBJECT_ERROR"
