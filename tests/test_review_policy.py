from agent_app.models.role_schemas import (
    ComposeOutput,
    ReviewIssue,
    ReviewIssueCode,
    ReviewOutput,
    ReviewSeverity,
)
from agent_app.review_policy import ReviewPolicyDecision, ReviewPolicyV1


def draft(answer: str, citations: list[dict] | None = None) -> ComposeOutput:
    return ComposeOutput.model_validate(
        {
            "answer": answer,
            "citations": citations or [],
            "limitations": [],
            "requires_human_confirmation": False,
        }
    )


def evidence(evidence_type: str, reference_id: str, **data: object) -> dict:
    return {
        "evidence_type": evidence_type,
        "source": "test",
        "reference_id": reference_id,
        "data": data,
    }


def model_review(*issues: ReviewIssue) -> ReviewOutput:
    blocked = any(item.severity is ReviewSeverity.BLOCKING for item in issues)
    return ReviewOutput(
        passed=not blocked,
        issues=list(issues),
        requires_human_confirmation=False,
    )


def issue(
    code: ReviewIssueCode,
    severity: ReviewSeverity = ReviewSeverity.BLOCKING,
    *,
    evidence_ids: list[str] | None = None,
) -> ReviewIssue:
    return ReviewIssue(
        code=code,
        severity=severity,
        message="模型发现潜在问题",
        evidence_ids=evidence_ids or [],
    )


def decide(
    answer: str,
    evidences: list[dict],
    review: ReviewOutput | None,
    *,
    sufficient: bool = True,
    write: bool = False,
):
    return ReviewPolicyV1().evaluate(
        draft=draft(answer),
        evidence=evidences,
        review=review,
        evidence_sufficient=sufficient,
        write_operation=write,
    )


def test_supported_analysis_with_strong_wording_is_warn_not_block() -> None:
    analysis = evidence(
        "ANALYSIS_RESULT",
        "risk-signals",
        signals=[{"risk_code": "PRICE", "matched": True, "risk_level": "MEDIUM"}],
    )

    result = decide(
        "系统已识别价格风险，风险等级为中等。",
        [analysis],
        model_review(issue(ReviewIssueCode.ANALYSIS_AS_FACT)),
    )

    assert result.decision is ReviewPolicyDecision.WARN
    assert result.issues[0].original_severity == "BLOCKING"


def test_explicit_tool_fact_conflict_is_block() -> None:
    tool = evidence("MCP_TOOL_RESULT", "request", status="COMPLETED")

    result = decide(
        "当前状态为待采购。",
        [tool],
        model_review(
            issue(ReviewIssueCode.ANALYSIS_AS_FACT, ReviewSeverity.WARNING)
        ),
    )

    assert result.decision is ReviewPolicyDecision.BLOCK
    assert any(item.code == "VERIFIED_FACT_CONFLICT" for item in result.issues)


def test_mandatory_claim_without_knowledge_is_block() -> None:
    result = decide(
        "制度规定必须立即终止采购，并认定违规。",
        [evidence("ANALYSIS_RESULT", "risk", matched=True)],
        model_review(issue(ReviewIssueCode.MISSING_EVIDENCE)),
    )

    assert result.decision is ReviewPolicyDecision.BLOCK


def test_existing_knowledge_with_minor_citation_issue_is_warn() -> None:
    knowledge = evidence("RAG_KNOWLEDGE", "K1", citation="K1", content="需要人工复核。")

    result = decide(
        "根据制度要求需要人工复核。",
        [knowledge],
        model_review(issue(ReviewIssueCode.MISSING_EVIDENCE)),
    )

    assert result.decision is ReviewPolicyDecision.WARN


def test_invisible_evidence_and_real_evidence_conflict_are_block() -> None:
    invisible = decide(
        "当前状态为已完成。",
        [evidence("MCP_TOOL_RESULT", "T1", status="COMPLETED")],
        model_review(
            issue(ReviewIssueCode.INVISIBLE_EVIDENCE, evidence_ids=["hidden-result"])
        ),
    )
    conflict = decide(
        "当前状态需要进一步确认。",
        [
            evidence("MCP_TOOL_RESULT", "T1", status="COMPLETED"),
            evidence("RAG_KNOWLEDGE", "K1", citation="K1", status="PENDING_PURCHASE"),
        ],
        model_review(
            issue(ReviewIssueCode.RAG_TOOL_CONFLICT, evidence_ids=["T1", "K1"])
        ),
    )

    assert invisible.decision is ReviewPolicyDecision.BLOCK
    assert conflict.decision is ReviewPolicyDecision.BLOCK


def test_multi_issue_aggregation_uses_policy_decisions_not_warning_count() -> None:
    tool = evidence("MCP_TOOL_RESULT", "T1", status="COMPLETED")
    warnings = model_review(
        issue(ReviewIssueCode.OMITTED_CONSTRAINT, ReviewSeverity.WARNING),
        issue(ReviewIssueCode.HUMAN_CONFIRMATION_REQUIRED, ReviewSeverity.WARNING),
    )

    warned = decide("当前状态为已完成，建议人工确认。", [tool], warnings)
    passed = decide("当前状态为已完成。", [tool], model_review())

    assert warned.decision is ReviewPolicyDecision.WARN
    assert len(warned.issues) == 2
    assert passed.decision is ReviewPolicyDecision.PASS


def test_review_unavailable_is_explicit_for_read_and_write_paths() -> None:
    tool = evidence("MCP_TOOL_RESULT", "T1", status="COMPLETED")

    read = decide("当前状态为已完成。", [tool], None)
    write = decide("采购草稿已准备，等待确认。", [tool], None, write=True)

    assert read.decision is ReviewPolicyDecision.REVIEW_UNAVAILABLE
    assert read.write_operation is False
    assert write.decision is ReviewPolicyDecision.REVIEW_UNAVAILABLE
    assert write.write_operation is True
