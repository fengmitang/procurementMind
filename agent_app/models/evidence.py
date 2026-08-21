from dataclasses import dataclass
from typing import Any

_TOOL_EVIDENCE_TYPE = "MCP_TOOL_RESULT"
_KNOWLEDGE_EVIDENCE_TYPE = "RAG_KNOWLEDGE"
_ANALYSIS_EVIDENCE_TYPE = "ANALYSIS_RESULT"
_INVESTIGATION_PREFIX = "INVESTIGATION_"
_INVESTIGATION_KNOWLEDGE_KIND = "KNOWLEDGE_RULE"
_INVESTIGATION_ANALYSIS_KINDS = frozenset({"RISK_SIGNALS"})


@dataclass(frozen=True)
class ModelEvidenceView:
    """Canonical, read-only evidence view consumed by Compose and Review."""

    visible_evidence: list[dict[str, Any]]
    tool_evidence: list[dict[str, Any]]
    knowledge_evidence: list[dict[str, Any]]
    analysis_evidence: list[dict[str, Any]]
    citation_ids: frozenset[str]


def model_evidence_contract() -> dict[str, Any]:
    return {
        "knowledge": {
            "evidence_type": _KNOWLEDGE_EVIDENCE_TYPE,
            "citation_required": True,
            "citation_namespace": "K",
        },
        "tool": {
            "evidence_type": _TOOL_EVIDENCE_TYPE,
            "citation_required": False,
            "tool_citation_supported": False,
            "verification": "compare_claims_with_visible_tool_data",
            "direct_fact_includes": [
                "fields_explicitly_returned_by_a_successful_tool",
                "backend_computed_matches_levels_thresholds_metrics_counts_and_ratios",
                "faithful_business_language_translation_or_comparison_of_returned_values",
                "allowed_action_presence_or_absence",
            ],
        },
        "analysis": {
            "evidence_type": _ANALYSIS_EVIDENCE_TYPE,
            "citation_required": False,
            "analysis_citation_supported": False,
            "verification": "compare_claims_with_visible_program_analysis",
            "direct_conclusion_includes": [
                "explicitly_computed_signal_match_or_non_match",
                "computed_risk_level_threshold_metric_count_ratio_or_comparison",
                "faithful_summary_of_the_returned_analysis_result",
            ],
            "does_not_support": [
                "policy_process_or_mandatory_action_not_present_in_knowledge_evidence",
                "causal_or_violation_conclusion_not_present_in_the_analysis_result",
                "claims_contradicting_visible_tool_or_analysis_data",
            ],
        },
        "advisory_text": (
            "clearly_non_binding_suggestions_are_not_backend_actions_or_policy_requirements"
        ),
        "rag_tool_conflict": "only_mutually_exclusive_claims_about_same_fact",
    }


def normalize_model_evidence(evidence: list[dict[str, Any]]) -> ModelEvidenceView:
    visible: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    knowledge: list[dict[str, Any]] = []
    analysis: list[dict[str, Any]] = []
    citation_ids: set[str] = set()

    for item in evidence:
        normalized = _normalize_item(item)
        visible.append(normalized)
        evidence_type = normalized.get("evidence_type")
        if evidence_type == _TOOL_EVIDENCE_TYPE:
            tools.append(normalized)
        elif evidence_type == _KNOWLEDGE_EVIDENCE_TYPE:
            knowledge.append(normalized)
            citation_ids.update(_knowledge_citation_ids(normalized))
        elif evidence_type == _ANALYSIS_EVIDENCE_TYPE:
            analysis.append(normalized)

    return ModelEvidenceView(
        visible_evidence=visible,
        tool_evidence=tools,
        knowledge_evidence=knowledge,
        analysis_evidence=analysis,
        citation_ids=frozenset(citation_ids),
    )


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    evidence_type = item.get("evidence_type")
    if evidence_type in {
        _TOOL_EVIDENCE_TYPE,
        _KNOWLEDGE_EVIDENCE_TYPE,
        _ANALYSIS_EVIDENCE_TYPE,
    }:
        return item
    if not isinstance(evidence_type, str) or not evidence_type.startswith(
        _INVESTIGATION_PREFIX
    ):
        return item

    envelope = item.get("data")
    if not isinstance(envelope, dict) or envelope.get("status") != "SUCCESS":
        return item

    kind = envelope.get("kind")
    if not isinstance(kind, str):
        kind = evidence_type.removeprefix(_INVESTIGATION_PREFIX)
    payload = envelope.get("data")
    if kind == _INVESTIGATION_KNOWLEDGE_KIND and isinstance(payload, dict):
        return {
            "evidence_type": _KNOWLEDGE_EVIDENCE_TYPE,
            "source": item.get("source", envelope.get("source", "")),
            "reference_id": envelope.get("evidence_id") or item.get("reference_id"),
            "data": payload,
        }
    if kind in _INVESTIGATION_ANALYSIS_KINDS and isinstance(payload, dict):
        return {
            "evidence_type": _ANALYSIS_EVIDENCE_TYPE,
            "source": item.get("source", envelope.get("source", "")),
            "reference_id": envelope.get("evidence_id") or item.get("reference_id"),
            "data": payload,
        }
    if isinstance(envelope.get("tool_name"), str) and payload is not None:
        return {
            "evidence_type": _TOOL_EVIDENCE_TYPE,
            "source": item.get("source", envelope.get("source", "")),
            "reference_id": envelope.get("evidence_id") or item.get("reference_id"),
            "data": payload,
        }
    return item


def _knowledge_citation_ids(item: dict[str, Any]) -> set[str]:
    values: list[Any] = [item.get("reference_id")]
    data = item.get("data")
    if isinstance(data, dict):
        values.append(data.get("citation"))
        citations = data.get("citations")
        if isinstance(citations, list):
            values.extend(citations)

    citation_ids: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("citation_id")
        if isinstance(value, str) and _is_knowledge_citation_id(value):
            citation_ids.add(value)
    return citation_ids


def _is_knowledge_citation_id(value: str) -> bool:
    return len(value) > 1 and value[0] == "K" and value[1:].isdigit()
