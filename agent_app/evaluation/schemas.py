from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    input: dict[str, JsonValue]
    expected_subset: dict[str, JsonValue]


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    passed: bool
    duration_ms: int = Field(ge=0)
    mismatches: list[str] = Field(default_factory=list)
    error_code: str | None = None


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str
    total: int
    passed: int
    failed: int
    pass_rate: float = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    results: list[EvaluationCaseResult]


class EvaluationSuiteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str
    status: Literal["PASSED", "FAILED", "BLOCKED"]
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    duration_ms: int = Field(default=0, ge=0)
    reason: str | None = None
    results: list[EvaluationCaseResult] = Field(default_factory=list)


class UnifiedEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str
    mode: Literal["DETERMINISTIC", "MODEL"]
    generated_at: datetime
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    blocked_suites: int = Field(ge=0)
    suites: list[EvaluationSuiteSummary]


class SuiteBaselineExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_total: int = Field(ge=0)
    minimum_pass_rate: float = Field(ge=0, le=1)
    maximum_failed: int = Field(ge=0)
    expected_status: Literal["PASSED", "FAILED", "BLOCKED"]


class EvaluationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_version: str
    mode: Literal["DETERMINISTIC", "MODEL"]
    suites: dict[str, SuiteBaselineExpectation]


class BaselineComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_version: str
    passed: bool
    mismatches: list[str] = Field(default_factory=list)
