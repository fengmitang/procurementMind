from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mcp.types import ToolAnnotations


class ToolNamespace(StrEnum):
    PROCUREMENT = "procurement"
    PRODUCT = "product"
    SUPPLIER = "supplier"
    ANALYTICS = "analytics"


class ToolFactKind(StrEnum):
    IDENTITY_CONTEXT = "identity_context"
    REALTIME_FACT = "realtime_fact"
    DERIVED_ANALYSIS = "derived_analysis"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    namespace: ToolNamespace
    fact_kind: ToolFactKind

    @property
    def protocol_meta(self) -> dict[str, Any]:
        return {
            "procurementMind": {
                "namespace": self.namespace.value,
                "factKind": self.fact_kind.value,
                "sourceOfTruth": "procurement_backend",
                "visibility": "backend_enforced",
                "authoritative": True,
                "ragBoundary": "not_a_knowledge_source",
                "requiresConfirmation": False,
            }
        }


TOOL_CATALOG = {
    descriptor.name: descriptor
    for descriptor in (
        ToolDescriptor(
            "get_current_user",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.IDENTITY_CONTEXT,
        ),
        ToolDescriptor(
            "get_purchase_request",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.REALTIME_FACT,
        ),
        ToolDescriptor(
            "get_purchase_timeline",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.REALTIME_FACT,
        ),
        ToolDescriptor(
            "search_purchase_records",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.REALTIME_FACT,
        ),
        ToolDescriptor(
            "recommend_purchase_history",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "get_requirement_risk_signals",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "get_similar_cases",
            ToolNamespace.PROCUREMENT,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "recommend_products",
            ToolNamespace.PRODUCT,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "recommend_suppliers",
            ToolNamespace.SUPPLIER,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "get_supplier_performance",
            ToolNamespace.SUPPLIER,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
        ToolDescriptor(
            "query_purchase_analytics",
            ToolNamespace.ANALYTICS,
            ToolFactKind.DERIVED_ANALYSIS,
        ),
    )
}


READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def get_tool_descriptor(name: str) -> ToolDescriptor:
    try:
        return TOOL_CATALOG[name]
    except KeyError as exc:
        raise ValueError(f"Unknown procurement tool: {name}") from exc


def tool_registration(name: str) -> dict[str, Any]:
    descriptor = get_tool_descriptor(name)
    return {
        "annotations": READ_ONLY_ANNOTATIONS,
        "meta": descriptor.protocol_meta,
    }
