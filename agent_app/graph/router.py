import re

from agent_app.graph.schemas import RouteType

_RISK_TERMS = ("风险", "异常", "违规", "围标", "串标", "黑名单", "舞弊", "调查")
_COMPLEX_TERMS = (
    "统计",
    "分析",
    "对比",
    "趋势",
    "排行",
    "汇总",
    "筛选",
    "平均",
    "履约",
    "相似案例",
    "哪些采购",
    "发起的采购",
)
_RECOMMENDATION_TERMS = (
    "推荐",
    "历史推荐",
    "参考历史",
    "历史参考",
    "以前一般",
    "历史上一般",
    "以前用什么",
)
_KNOWLEDGE_TERMS = (
    "制度",
    "流程",
    "规定",
    "规范",
    "如何",
    "为什么",
    "能否",
    "标准",
    "接下来",
    "怎么处理",
    "怎么办",
    "驳回后",
)
_REALTIME_TERMS = (
    "当前状态",
    "采购单状态",
    "采购申请状态",
    "需求单状态",
    "处理人",
    "经办人",
    "到哪一步",
    "进度",
    "历史采购",
    "这张采购单",
    "当前采购单",
    "这张申请",
    "当前申请",
)
_FORM_PREFILL_TERMS = (
    "预填采购申请",
    "填写采购申请",
    "生成采购申请草稿",
    "采购申请草稿",
    "我要采购",
    "想采购",
    "需要采购",
    "采购一批",
    "买一批",
    "申请采购",
)


class FirstVersionRouter:
    """Deterministic P0 router; a model-backed classifier can replace it later."""

    def classify(self, message: str) -> RouteType:
        normalized = re.sub(r"\s+", "", message.lower())
        has_risk = any(term in normalized for term in _RISK_TERMS)
        has_form_prefill = any(term in normalized for term in _FORM_PREFILL_TERMS)
        has_recommendation = any(term in normalized for term in _RECOMMENDATION_TERMS)
        has_complex = any(term in normalized for term in _COMPLEX_TERMS)
        has_knowledge = any(term in normalized for term in _KNOWLEDGE_TERMS)
        has_realtime = any(term in normalized for term in _REALTIME_TERMS) or bool(
            self.extract_requirement_id(message)
        )
        if has_recommendation:
            return RouteType.RECOMMENDATION
        if has_form_prefill:
            return RouteType.FORM_PREFILL
        if has_complex and any(marker in normalized for marker in ("排除黑名单", "剔除黑名单")):
            return RouteType.COMPLEX_QUERY
        if has_knowledge and has_risk and not has_realtime:
            return RouteType.KNOWLEDGE
        if has_risk:
            return RouteType.RISK_INVESTIGATION
        if has_complex:
            return RouteType.COMPLEX_QUERY
        if has_knowledge and has_realtime:
            return RouteType.HYBRID
        if has_realtime:
            return RouteType.REALTIME_BUSINESS
        return RouteType.KNOWLEDGE

    def should_use_model(self, message: str) -> bool:
        """Reserve the slower model router for queries without explicit route signals."""
        normalized = re.sub(r"\s+", "", message.lower())
        terms = (
            *_RISK_TERMS,
            *_COMPLEX_TERMS,
            *_KNOWLEDGE_TERMS,
            *_REALTIME_TERMS,
            *_FORM_PREFILL_TERMS,
            *_RECOMMENDATION_TERMS,
        )
        return not any(term in normalized for term in terms) and not bool(
            self.extract_requirement_id(message)
        )

    @staticmethod
    def is_recommendation(message: str) -> bool:
        normalized = re.sub(r"\s+", "", message.lower())
        return any(term in normalized for term in _RECOMMENDATION_TERMS)

    @staticmethod
    def is_recommendation_confirmation(message: str) -> bool:
        normalized = re.sub(r"[\s，。！？!?]+", "", message.lower())
        return normalized in {"需要", "需要推荐", "需要历史推荐"}

    @staticmethod
    def extract_requirement_id(message: str) -> int | None:
        labeled = re.search(
            r"(?:采购(?:申请|单)?|需求单|申请)\D{0,12}(\d{1,18})(?!\d)",
            message,
        )
        if labeled:
            return int(labeled.group(1))
        standalone = re.search(r"(?<!\d)(\d{4,18})(?!\d)", message)
        return int(standalone.group(1)) if standalone else None
