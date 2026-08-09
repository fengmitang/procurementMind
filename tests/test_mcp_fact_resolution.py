import pytest

from agent_app.mcp.fact_resolution import (
    EvidenceDomain,
    EvidenceResolutionStatus,
    resolve_rag_tool_evidence,
)


@pytest.mark.parametrize(
    "domain",
    [domain for domain in EvidenceDomain if domain is not EvidenceDomain.STABLE_RULE],
)
def test_realtime_domains_never_fall_back_to_rag(domain: EvidenceDomain) -> None:
    result = resolve_rag_tool_evidence(
        domain=domain,
        rag_value="文档中的旧值",
        tool_value=None,
    )

    assert result.status is EvidenceResolutionStatus.UNRESOLVED
    assert result.selected_value is None
    assert result.authoritative_source is None
    assert "不得使用 RAG" in result.warning


def test_tool_fact_overrides_conflicting_rag_text() -> None:
    result = resolve_rag_tool_evidence(
        domain=EvidenceDomain.BLACKLIST_STATUS,
        rag_value="未列入黑名单",
        tool_value="已列入黑名单",
    )

    assert result.status is EvidenceResolutionStatus.TOOL_OVERRIDES_RAG
    assert result.selected_value == "已列入黑名单"
    assert result.authoritative_source == "procurement_backend"
    assert result.warning is not None


def test_stable_rule_uses_cited_rag_evidence() -> None:
    result = resolve_rag_tool_evidence(
        domain=EvidenceDomain.STABLE_RULE,
        rag_value="审批前必须完成风险核实",
        tool_value="后端当前没有规则字段",
    )

    assert result.status is EvidenceResolutionStatus.RAG_AUTHORITATIVE
    assert result.selected_value == "审批前必须完成风险核实"
    assert result.authoritative_source == "rag"
