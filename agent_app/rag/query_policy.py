from __future__ import annotations

import re

QUERY_POLICY_VERSION = "conservative-v1"

_REFERENCE_SIGNALS = (
    "这个",
    "这份",
    "这张",
    "这些",
    "那个",
    "上述",
    "前面",
    "刚才",
    "上一条",
    "上一个",
    "它",
    "他们",
    "该事项",
    "该问题",
    "当前这个",
    "继续",
    "接着",
    "然后呢",
    "那怎么办",
)
_COMPOUND_SIGNALS = (
    "并且",
    "同时",
    "以及",
    "分别",
    "对比",
    "比较",
    "或者",
    "还是",
    "一方面",
    "另一方面",
)
_DOMAIN_SIGNALS = (
    "采购",
    "申请",
    "需求",
    "供应商",
    "楼长",
    "审批",
    "驳回",
    "黑名单",
    "验收",
    "合同",
    "询价",
    "比价",
    "设备",
    "付款",
    "入库",
    "制度",
    "流程",
)
_QUESTION_SIGNALS = (
    "如何",
    "怎么",
    "什么",
    "哪些",
    "为何",
    "为什么",
    "是否",
    "能否",
    "可以",
    "要求",
    "规则",
    "流程",
    "步骤",
    "条件",
    "标准",
    "多久",
    "谁",
)
_MULTI_CLAUSE_PATTERN = re.compile(r"[，,；;].*(?:如何|怎么|什么|哪些|是否|能否|为什么)")


def normalize_query(query: str) -> str:
    return " ".join(query.split())


def can_skip_query_rewrite(query: str) -> bool:
    """Return true only for a self-contained, single-intent procurement question."""

    value = normalize_query(query)
    if not 6 <= len(value) <= 120:
        return False
    if any(signal in value for signal in _REFERENCE_SIGNALS):
        return False
    if any(signal in value for signal in _COMPOUND_SIGNALS):
        return False
    if "如果" in value and any(signal in value for signal in ("那么", "就", "又", "还")):
        return False
    if _MULTI_CLAUSE_PATTERN.search(value):
        return False
    if not any(signal in value for signal in _DOMAIN_SIGNALS):
        return False
    return any(signal in value for signal in _QUESTION_SIGNALS)
