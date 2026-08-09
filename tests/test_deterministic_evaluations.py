from pathlib import Path

import pytest

from agent_app.evaluation import (
    EvaluationBaseline,
    build_unified_report,
    compare_with_baseline,
)
from agent_app.evaluation.deterministic import (
    load_deterministic_cases,
    run_deterministic_suites,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_unified_deterministic_report_matches_explicit_baseline() -> None:
    cases = load_deterministic_cases(ROOT / "tests" / "fixtures")
    reports = await run_deterministic_suites(
        router_cases=cases.router,
        tool_cases=cases.tool,
        analysis_cases=cases.analysis,
        risk_cases=cases.risk,
    )
    report = build_unified_report(reports)
    baseline = EvaluationBaseline.model_validate_json(
        (ROOT / "docs" / "baseline" / "deterministic-evaluation-baseline-v0.2.json").read_text(
            encoding="utf-8"
        )
    )
    comparison = compare_with_baseline(report, baseline)

    assert report.total == 25
    assert report.passed == 25
    assert report.failed == 0
    assert report.blocked_suites == 0
    assert comparison.passed is True
    assert comparison.mismatches == []


@pytest.mark.asyncio
async def test_baseline_comparison_reports_regression_without_updating_baseline() -> None:
    cases = load_deterministic_cases(ROOT / "tests" / "fixtures")
    reports = await run_deterministic_suites(
        router_cases=cases.router[:1],
        tool_cases=cases.tool,
        analysis_cases=cases.analysis,
        risk_cases=cases.risk,
    )
    report = build_unified_report(reports)
    baseline = EvaluationBaseline.model_validate_json(
        (ROOT / "docs" / "baseline" / "deterministic-evaluation-baseline-v0.2.json").read_text(
            encoding="utf-8"
        )
    )

    comparison = compare_with_baseline(report, baseline)

    assert comparison.passed is False
    assert "router.total: expected=10, actual=1" in comparison.mismatches
