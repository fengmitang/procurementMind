from agent_app.evaluation.risk import RiskEvaluationExpectation, RiskEvaluationRunner
from agent_app.investigation.schemas import (
    ProgramReviewResult,
    RiskInvestigationOutput,
    RiskSummaryItem,
)


def item(code: str) -> RiskSummaryItem:
    return RiskSummaryItem(
        risk_code=code,
        risk_type="测试风险",
        risk_level="MEDIUM",
        backend_rule_matched=True,
        facts={"value": 1},
        metrics={},
        related_record_ids=[91001],
        data_sources=["/api/v1/requirements/91009/risk-signals"],
        applicable_rule={"threshold": 1},
        possible_causes=["可能原因尚需核实"],
        information_complete=False,
        information_gaps=["缺少制度证据"],
        human_checks=["核对原始记录"],
    )


def test_risk_evaluation_calculates_recall_false_positive_and_coverage() -> None:
    output = RiskInvestigationOutput(
        requirement_id=91009,
        answer="风险调查完成，不代表审批结论。",
        summary_items=[item("PRICE_DEVIATION"), item("DELIVERY_DELAY")],
        evidence=[],
        review=ProgramReviewResult(passed=True, checked_items=2),
        complete=False,
    )
    expectation = RiskEvaluationExpectation(
        case_id="risk-case",
        expected_risk_codes={"PRICE_DEVIATION", "QUANTITY_ANOMALY"},
        forbidden_risk_codes={"DELIVERY_DELAY"},
    )

    metrics = RiskEvaluationRunner().evaluate(expectation, output)

    assert metrics.true_positive == 1
    assert metrics.false_positive == 1
    assert metrics.missed == 1
    assert metrics.recall == 0.5
    assert metrics.precision == 0.5
    assert metrics.evidence_coverage == 1
    assert metrics.approval_overreach_count == 0
