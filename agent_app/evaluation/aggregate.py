from datetime import UTC, datetime

from agent_app.evaluation.schemas import (
    BaselineComparison,
    EvaluationBaseline,
    EvaluationReport,
    EvaluationSuiteSummary,
    UnifiedEvaluationReport,
)


def build_unified_report(
    reports: list[EvaluationReport],
    *,
    blocked_suites: dict[str, str] | None = None,
    report_version: str = "1.0",
) -> UnifiedEvaluationReport:
    suites = [
        EvaluationSuiteSummary(
            suite_name=report.suite_name,
            status="PASSED" if report.failed == 0 else "FAILED",
            total=report.total,
            passed=report.passed,
            failed=report.failed,
            pass_rate=report.pass_rate,
            duration_ms=report.duration_ms,
            results=report.results,
        )
        for report in reports
    ]
    suites.extend(
        EvaluationSuiteSummary(
            suite_name=name,
            status="BLOCKED",
            total=0,
            passed=0,
            failed=0,
            reason=reason,
        )
        for name, reason in (blocked_suites or {}).items()
    )
    total = sum(suite.total for suite in suites if suite.status != "BLOCKED")
    passed = sum(suite.passed for suite in suites if suite.status != "BLOCKED")
    failed = sum(suite.failed for suite in suites if suite.status != "BLOCKED")
    return UnifiedEvaluationReport(
        report_version=report_version,
        mode="DETERMINISTIC",
        generated_at=datetime.now(UTC),
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=passed / total if total else 0,
        blocked_suites=sum(suite.status == "BLOCKED" for suite in suites),
        suites=suites,
    )


def compare_with_baseline(
    report: UnifiedEvaluationReport,
    baseline: EvaluationBaseline,
) -> BaselineComparison:
    mismatches: list[str] = []
    if report.mode != baseline.mode:
        mismatches.append(f"mode: expected={baseline.mode}, actual={report.mode}")
    current = {suite.suite_name: suite for suite in report.suites}
    for name, expectation in baseline.suites.items():
        suite = current.get(name)
        if suite is None:
            mismatches.append(f"{name}: missing suite")
            continue
        if suite.status != expectation.expected_status:
            mismatches.append(
                f"{name}.status: expected={expectation.expected_status}, actual={suite.status}"
            )
        if suite.total != expectation.expected_total:
            mismatches.append(
                f"{name}.total: expected={expectation.expected_total}, actual={suite.total}"
            )
        if suite.failed > expectation.maximum_failed:
            mismatches.append(
                f"{name}.failed: maximum={expectation.maximum_failed}, actual={suite.failed}"
            )
        if suite.pass_rate is not None and suite.pass_rate < expectation.minimum_pass_rate:
            mismatches.append(
                f"{name}.pass_rate: minimum={expectation.minimum_pass_rate}, "
                f"actual={suite.pass_rate}"
            )
    unexpected = sorted(set(current) - set(baseline.suites))
    mismatches.extend(f"{name}: unexpected suite" for name in unexpected)
    return BaselineComparison(
        baseline_version=baseline.baseline_version,
        passed=not mismatches,
        mismatches=mismatches,
    )
