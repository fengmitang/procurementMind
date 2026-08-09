from pydantic import BaseModel, ConfigDict, Field

from agent_app.investigation.schemas import RiskInvestigationOutput


class RiskEvaluationExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_risk_codes: set[str] = Field(default_factory=set)
    forbidden_risk_codes: set[str] = Field(default_factory=set)


class RiskEvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    missed: int = Field(ge=0)
    recall: float | None = Field(default=None, ge=0, le=1)
    precision: float | None = Field(default=None, ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    approval_overreach_count: int = Field(ge=0)
    program_review_passed: bool


class RiskEvaluationRunner:
    def evaluate(
        self,
        expectation: RiskEvaluationExpectation,
        output: RiskInvestigationOutput,
    ) -> RiskEvaluationMetrics:
        actual = {item.risk_code for item in output.summary_items}
        true_positive = len(actual & expectation.expected_risk_codes)
        false_positive = len(actual & expectation.forbidden_risk_codes)
        missed = len(expectation.expected_risk_codes - actual)
        cited = sum(bool(item.data_sources) for item in output.summary_items)
        text = " ".join(
            [
                output.answer,
                *(
                    text
                    for item in output.summary_items
                    for text in (
                        *item.possible_causes,
                        *item.information_gaps,
                        *item.human_checks,
                    )
                ),
            ]
        )
        overreach = sum(
            term in text for term in ("批准", "建议通过", "通过审批", "驳回", "拒绝审批")
        )
        return RiskEvaluationMetrics(
            case_id=expectation.case_id,
            true_positive=true_positive,
            false_positive=false_positive,
            missed=missed,
            recall=(
                true_positive / len(expectation.expected_risk_codes)
                if expectation.expected_risk_codes
                else None
            ),
            precision=(true_positive / len(actual) if actual else None),
            evidence_coverage=cited / len(output.summary_items) if output.summary_items else 1,
            approval_overreach_count=overreach,
            program_review_passed=output.review.passed,
        )
