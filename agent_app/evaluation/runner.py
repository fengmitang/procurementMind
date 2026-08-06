import time
from typing import Protocol

from pydantic import JsonValue

from agent_app.evaluation.schemas import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationReport,
)


class EvaluationSubject(Protocol):
    async def execute(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]: ...


class EvaluationRunner:
    async def run(
        self,
        suite_name: str,
        cases: list[EvaluationCase],
        subject: EvaluationSubject,
    ) -> EvaluationReport:
        started = time.perf_counter()
        results: list[EvaluationCaseResult] = []
        for case in cases:
            case_started = time.perf_counter()
            try:
                actual = await subject.execute(case.input)
                mismatches = self._compare(case.expected_subset, actual)
                results.append(
                    EvaluationCaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        passed=not mismatches,
                        duration_ms=self._elapsed_ms(case_started),
                        mismatches=mismatches,
                    )
                )
            except Exception as exc:
                results.append(
                    EvaluationCaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        passed=False,
                        duration_ms=self._elapsed_ms(case_started),
                        error_code=getattr(exc, "code", "EVALUATION_SUBJECT_ERROR"),
                    )
                )
        passed = sum(item.passed for item in results)
        return EvaluationReport(
            suite_name=suite_name,
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            pass_rate=passed / len(results) if results else 0,
            duration_ms=self._elapsed_ms(started),
            results=results,
        )

    @classmethod
    def _compare(
        cls,
        expected: dict[str, JsonValue],
        actual: dict[str, JsonValue],
        prefix: str = "",
    ) -> list[str]:
        mismatches: list[str] = []
        for key, expected_value in expected.items():
            path = f"{prefix}.{key}" if prefix else key
            if key not in actual:
                mismatches.append(f"{path}: missing")
                continue
            actual_value = actual[key]
            if isinstance(expected_value, dict) and isinstance(actual_value, dict):
                mismatches.extend(cls._compare(expected_value, actual_value, path))
            elif actual_value != expected_value:
                mismatches.append(f"{path}: expected={expected_value!r}, actual={actual_value!r}")
        return mismatches

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
