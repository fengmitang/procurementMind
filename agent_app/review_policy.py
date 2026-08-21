import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_app.models.evidence import ModelEvidenceView, normalize_model_evidence
from agent_app.models.role_schemas import ComposeOutput, ReviewIssue, ReviewOutput


class ReviewPolicyDecision(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    REVIEW_UNAVAILABLE = "REVIEW_UNAVAILABLE"


class ReviewPolicyIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    decision: ReviewPolicyDecision
    reason: str
    original_severity: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewPolicyDecision
    issues: list[ReviewPolicyIssue] = Field(default_factory=list)
    review_available: bool = True
    write_operation: bool = False


class ReviewPolicyV1:
    """Deterministically adjudicate model findings against visible evidence."""

    _mandatory_claim = re.compile(
        r"(?:制度|规定|规范|流程|政策|职责).{0,12}(?:要求|必须|不得|应当|禁止)|"
        r"(?:必须|不得|应当|严禁|违规|合规|已构成违规|认定违规)"
    )
    _executed_action = re.compile(r"(?:已经|已)(?:提交|审批|批准|驳回|执行|创建|入库|完成)")
    _internal_reference = re.compile(
        r"(?:Prompt|Chunk|Router|Graph|evidence|agent_app|[/\\][\w.-]+\.md)",
        re.IGNORECASE,
    )

    def trusted_revised_answer(
        self,
        revised_answer: str | None,
        evidence: list[dict[str, Any]],
    ) -> str | None:
        if not revised_answer or self._internal_reference.search(revised_answer):
            return None
        view = normalize_model_evidence(evidence)
        if self._has_explicit_fact_conflict(revised_answer, view):
            return None
        if not view.knowledge_evidence and self._mandatory_claim.search(revised_answer):
            return None
        return revised_answer

    def evaluate(
        self,
        *,
        draft: ComposeOutput,
        evidence: list[dict[str, Any]],
        review: ReviewOutput | None,
        evidence_sufficient: bool,
        write_operation: bool,
    ) -> ReviewPolicyResult:
        view = normalize_model_evidence(evidence)
        if review is None:
            return ReviewPolicyResult(
                decision=ReviewPolicyDecision.REVIEW_UNAVAILABLE,
                review_available=False,
                write_operation=write_operation,
            )

        adjudicated = [
            self._adjudicate_issue(
                issue,
                draft=draft,
                view=view,
                evidence_sufficient=evidence_sufficient,
                write_operation=write_operation,
            )
            for issue in review.issues
        ]
        if self._has_explicit_fact_conflict(draft.answer, view):
            adjudicated.append(
                ReviewPolicyIssue(
                    code="VERIFIED_FACT_CONFLICT",
                    decision=ReviewPolicyDecision.BLOCK,
                    reason="回答与可见 Tool/Analysis 的明确事实冲突",
                )
            )
        if not view.knowledge_evidence and self._mandatory_claim.search(draft.answer):
            adjudicated.append(
                ReviewPolicyIssue(
                    code="UNSUPPORTED_MANDATORY_CLAIM",
                    decision=ReviewPolicyDecision.BLOCK,
                    reason="回答在没有 Knowledge Evidence 时声称制度、强制或违规结论",
                )
            )
        decision = self._aggregate(adjudicated)
        return ReviewPolicyResult(
            decision=decision,
            issues=self._deduplicate(adjudicated),
            write_operation=write_operation,
        )

    def _adjudicate_issue(
        self,
        issue: ReviewIssue,
        *,
        draft: ComposeOutput,
        view: ModelEvidenceView,
        evidence_sufficient: bool,
        write_operation: bool,
    ) -> ReviewPolicyIssue:
        code = issue.code.value
        decision = ReviewPolicyDecision.WARN
        reason = "模型发现非硬阻断问题，保留为警告"

        if code == "AUTHORITY_EXCEEDED":
            if write_operation or self._executed_action.search(draft.answer):
                decision = ReviewPolicyDecision.BLOCK
                reason = "回答涉及未经确认的业务写操作或声称已执行正式动作"
        elif code == "INVISIBLE_EVIDENCE":
            if self._has_invisible_reference(issue, draft, view):
                decision = ReviewPolicyDecision.BLOCK
                reason = "回答使用了当前不可见的证据或引用"
        elif code == "RAG_TOOL_CONFLICT":
            if self._has_referenced_evidence_conflict(issue, view):
                decision = ReviewPolicyDecision.BLOCK
                reason = "被引用的可见证据对同一事实存在真实冲突"
        elif code == "MISSING_EVIDENCE":
            if not evidence_sufficient:
                decision = ReviewPolicyDecision.BLOCK
                reason = "完成请求所需的证据链本身不充分"
            elif not view.knowledge_evidence and self._mandatory_claim.search(draft.answer):
                decision = ReviewPolicyDecision.BLOCK
                reason = "无 Knowledge Evidence 却声称制度、强制或违规结论"
            elif view.knowledge_evidence:
                reason = "Knowledge Evidence 存在，引用或表达问题降为警告"
            elif view.analysis_evidence:
                reason = "核心结论已有 Analysis Evidence，证据疑虑降为警告"
        elif code == "ANALYSIS_AS_FACT":
            if self._has_explicit_fact_conflict(draft.answer, view):
                decision = ReviewPolicyDecision.BLOCK
                reason = "回答与可见 Tool/Analysis 事实明确冲突"
            elif not view.tool_evidence and not view.analysis_evidence:
                decision = ReviewPolicyDecision.BLOCK
                reason = "回答缺少任何 Tool/Analysis 事实支撑"
            else:
                reason = "存在 Tool/Analysis 支撑，表达偏强降为警告"
        elif code == "HUMAN_CONFIRMATION_REQUIRED":
            reason = "保留人工确认要求，由 Graph 的确认链路执行"

        return ReviewPolicyIssue(
            code=code,
            decision=decision,
            reason=reason,
            original_severity=issue.severity.value,
            evidence_ids=issue.evidence_ids,
        )

    @staticmethod
    def _aggregate(issues: list[ReviewPolicyIssue]) -> ReviewPolicyDecision:
        if any(item.decision is ReviewPolicyDecision.BLOCK for item in issues):
            return ReviewPolicyDecision.BLOCK
        if any(item.decision is ReviewPolicyDecision.WARN for item in issues):
            return ReviewPolicyDecision.WARN
        return ReviewPolicyDecision.PASS

    @staticmethod
    def _deduplicate(issues: list[ReviewPolicyIssue]) -> list[ReviewPolicyIssue]:
        output: list[ReviewPolicyIssue] = []
        seen: set[tuple[str, ReviewPolicyDecision, str]] = set()
        for issue in issues:
            key = (issue.code, issue.decision, issue.reason)
            if key not in seen:
                seen.add(key)
                output.append(issue)
        return output

    @staticmethod
    def _visible_ids(view: ModelEvidenceView) -> set[str]:
        ids = set(view.citation_ids)
        for item in view.visible_evidence:
            reference_id = item.get("reference_id")
            if isinstance(reference_id, str):
                ids.add(reference_id)
        return ids

    def _has_invisible_reference(
        self,
        issue: ReviewIssue,
        draft: ComposeOutput,
        view: ModelEvidenceView,
    ) -> bool:
        visible = self._visible_ids(view)
        cited = {item.citation_id for item in draft.citations}
        return bool((set(issue.evidence_ids) | cited) - visible)

    def _has_referenced_evidence_conflict(
        self,
        issue: ReviewIssue,
        view: ModelEvidenceView,
    ) -> bool:
        selected = [
            item
            for item in view.visible_evidence
            if item.get("reference_id") in set(issue.evidence_ids)
        ]
        return len(selected) > 1 and self._structured_values_conflict(selected)

    @classmethod
    def _structured_values_conflict(cls, evidence: list[dict[str, Any]]) -> bool:
        values_by_key: dict[str, set[str]] = {}
        for item in evidence:
            flattened = cls._flatten_scalars(item.get("data"))
            for key, value in flattened.items():
                values_by_key.setdefault(key, set()).add(value)
        return any(len(values) > 1 for values in values_by_key.values())

    @classmethod
    def _flatten_scalars(cls, value: Any, prefix: str = "") -> dict[str, str]:
        output: dict[str, str] = {}
        if isinstance(value, dict):
            for key, child in value.items():
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                output.update(cls._flatten_scalars(child, child_prefix))
        elif isinstance(value, (str, int, float, bool)) and prefix:
            output[prefix] = str(value).lower()
        return output

    @staticmethod
    def _has_explicit_fact_conflict(answer: str, view: ModelEvidenceView) -> bool:
        normalized = answer.lower()
        for item in [*view.tool_evidence, *view.analysis_evidence]:
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            status = data.get("status")
            status_labels = {
                "DRAFT": "草稿",
                "PENDING_REVIEW": "待审批",
                "PENDING_PURCHASE": "待采购",
                "PURCHASING": "采购中",
                "PENDING_WAREHOUSE": "待入库",
                "COMPLETED": "已完成",
                "REJECTED": "已驳回",
            }
            if isinstance(status, str) and status in status_labels:
                other_labels = set(status_labels.values()) - {status_labels[status]}
                if any(f"当前状态为{label}" in normalized for label in other_labels):
                    return True
            signals = data.get("signals")
            if isinstance(signals, list):
                matches = {
                    signal.get("matched")
                    for signal in signals
                    if isinstance(signal, dict) and isinstance(signal.get("matched"), bool)
                }
                if matches == {True} and re.search(r"(?:系统|信号).{0,12}未命中", answer):
                    return True
                if matches == {False} and re.search(
                    r"(?:系统|信号).{0,12}(?:已命中|命中)", answer
                ):
                    return True
        return False
