from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceDomain(StrEnum):
    STABLE_RULE = "stable_rule"
    REALTIME_STATE = "realtime_state"
    CURRENT_ACTOR = "current_actor"
    CURRENT_PRICE = "current_price"
    PURCHASE_RECORD = "purchase_record"
    SUPPLIER_PROFILE = "supplier_profile"
    BLACKLIST_STATUS = "blacklist_status"
    REALTIME_STATISTIC = "realtime_statistic"


class EvidenceResolutionStatus(StrEnum):
    CONSISTENT = "consistent"
    TOOL_OVERRIDES_RAG = "tool_overrides_rag"
    RAG_AUTHORITATIVE = "rag_authoritative"
    UNRESOLVED = "unresolved"


class EvidenceResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvidenceResolutionStatus
    selected_value: str | None
    authoritative_source: str | None
    warning: str | None = None


def resolve_rag_tool_evidence(
    *,
    domain: EvidenceDomain,
    rag_value: str | None,
    tool_value: str | None,
) -> EvidenceResolution:
    """Apply the boundary between stable knowledge and procurement facts.

    The function deliberately does not infer a missing real-time value from RAG.
    """
    if domain is EvidenceDomain.STABLE_RULE:
        return EvidenceResolution(
            status=EvidenceResolutionStatus.RAG_AUTHORITATIVE,
            selected_value=rag_value,
            authoritative_source="rag" if rag_value is not None else None,
            warning=None if rag_value is not None else "未检索到可引用的稳定规则证据",
        )

    if tool_value is None:
        return EvidenceResolution(
            status=EvidenceResolutionStatus.UNRESOLVED,
            selected_value=None,
            authoritative_source=None,
            warning="实时事实工具未返回结果，不得使用 RAG 内容推测",
        )

    conflict = rag_value is not None and rag_value != tool_value
    return EvidenceResolution(
        status=(
            EvidenceResolutionStatus.TOOL_OVERRIDES_RAG
            if conflict
            else EvidenceResolutionStatus.CONSISTENT
        ),
        selected_value=tool_value,
        authoritative_source="procurement_backend",
        warning="RAG 内容与实时业务事实冲突，已采用采购后端结果" if conflict else None,
    )
