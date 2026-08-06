from typing import Any

from agent_app.investigation.schemas import (
    InvestigationEvidence,
    InvestigationEvidenceKind,
    ProgramReviewResult,
    ReviewFinding,
    RiskSummaryItem,
)

_FORBIDDEN_DECISIONS = ("批准", "通过审批", "建议通过", "驳回", "拒绝审批")


class ProgramEvidenceReviewer:
    def review(
        self,
        items: list[RiskSummaryItem],
        evidence: list[InvestigationEvidence],
    ) -> ProgramReviewResult:
        findings: list[ReviewFinding] = []
        risk_payload = self._risk_payload(evidence)
        signals = {
            signal.get("risk_code"): signal
            for signal in risk_payload.get("signals", [])
            if isinstance(signal, dict) and isinstance(signal.get("risk_code"), str)
        }
        for item in items:
            signal = signals.get(item.risk_code)
            if signal is None:
                findings.append(
                    self._finding(
                        "RISK_SOURCE_MISSING",
                        item.risk_code,
                        "摘要风险在后端风险信号中不存在",
                    )
                )
                continue
            for field, actual in (
                ("risk_type", item.risk_type),
                ("risk_level", item.risk_level),
                ("matched", item.backend_rule_matched),
                ("facts", item.facts),
                ("metrics", item.metrics),
                ("related_record_ids", item.related_record_ids),
                ("threshold", item.applicable_rule),
            ):
                if signal.get(field) != actual:
                    findings.append(
                        self._finding(
                            "RISK_FACT_MISMATCH",
                            item.risk_code,
                            f"摘要字段 {field} 与后端风险信号不一致",
                        )
                    )
            if not any(source.endswith("/risk-signals") for source in item.data_sources):
                findings.append(
                    self._finding(
                        "RISK_SOURCE_NOT_CITED",
                        item.risk_code,
                        "摘要未引用后端风险信号来源",
                    )
                )
            text = " ".join([*item.possible_causes, *item.information_gaps, *item.human_checks])
            if any(term in text for term in _FORBIDDEN_DECISIONS):
                findings.append(
                    self._finding(
                        "APPROVAL_DECISION_FORBIDDEN",
                        item.risk_code,
                        "风险摘要包含越权审批结论",
                        severity="HIGH",
                    )
                )
        return ProgramReviewResult(
            passed=not findings,
            checked_items=len(items),
            findings=findings,
        )

    @staticmethod
    def _risk_payload(evidence: list[InvestigationEvidence]) -> dict[str, Any]:
        for item in evidence:
            if item.kind is InvestigationEvidenceKind.RISK_SIGNALS and isinstance(item.data, dict):
                return item.data
        return {}

    @staticmethod
    def _finding(
        code: str,
        risk_code: str,
        message: str,
        *,
        severity: str = "ERROR",
    ) -> ReviewFinding:
        return ReviewFinding(
            code=code,
            severity=severity,
            risk_code=risk_code,
            message=message,
        )
