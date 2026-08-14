import json
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from pydantic import BaseModel

from agent_app.analysis.schemas import AnalysisPlan
from agent_app.models.protocols import (
    ModelMessage,
    ModelPurpose,
    StructuredModelRequest,
    StructuredModelResponse,
)
from agent_app.models.role_schemas import (
    ComposeOutput,
    QueryRewriteOutput,
    ReviewOutput,
    RouterOutput,
)
from agent_app.models.runner import StructuredModelRunError, StructuredModelRunner

OutputT = TypeVar("OutputT", bound=BaseModel)

_ROLE_MAX_OUTPUT_TOKENS: dict[ModelPurpose, int] = {
    ModelPurpose.ROUTER: 256,
    ModelPurpose.QUERY_REWRITE: 256,
    ModelPurpose.ANALYSIS_PLAN: 1200,
    ModelPurpose.ANALYSIS_REPLAN: 1200,
    ModelPurpose.COMPOSE: 1200,
    ModelPurpose.REVIEW: 800,
}
_ROLE_THINKING: dict[ModelPurpose, bool | None] = {
    ModelPurpose.ROUTER: False,
    ModelPurpose.QUERY_REWRITE: False,
    ModelPurpose.ANALYSIS_PLAN: None,
    ModelPurpose.ANALYSIS_REPLAN: None,
    ModelPurpose.COMPOSE: False,
    ModelPurpose.REVIEW: False,
}


class StructuredModelRoles:
    """Provider-neutral structured entry points for the five model roles."""

    def __init__(
        self,
        runner: StructuredModelRunner,
        trace_id: str,
        *,
        performance_optimizations_enabled: bool = True,
    ) -> None:
        self.runner = runner
        self.trace_id = trace_id
        self.performance_optimizations_enabled = performance_optimizations_enabled
        self._trace_id_context: ContextVar[str] = ContextVar(
            f"model_trace_id_{id(self)}", default=trace_id
        )
        self._call_metadata: ContextVar[dict[ModelPurpose, dict[str, Any]] | None] = ContextVar(
            f"model_call_metadata_{id(self)}", default=None
        )

    @property
    def cache_identity(self) -> str:
        return f"{self.runner.primary_model or 'configured-model'}|role-prompts-v2"

    def trace_metadata(self, purpose: ModelPurpose) -> dict[str, Any] | None:
        values = self._call_metadata.get() or {}
        value = values.get(purpose)
        return dict(value) if value else None

    @contextmanager
    def bind_trace_id(self, trace_id: str) -> Iterator[None]:
        trace_token = self._trace_id_context.set(trace_id)
        metadata_token = self._call_metadata.set({})
        try:
            yield
        finally:
            self._call_metadata.reset(metadata_token)
            self._trace_id_context.reset(trace_token)

    async def route(self, message: str) -> RouterOutput:
        output, _, _ = await self._run(
            ModelPurpose.ROUTER,
            RouterOutput,
            (
                "你是采购协同 Router。只按 Schema 分类，不回答问题。实时状态、处理人、价格、"
                "采购记录、供应商、黑名单和统计必须标记需要实时工具；制度和操作规则需要知识库。"
                "单条记录或单个对象的直接查询使用 REALTIME_BUSINESS；聚合统计、趋势、对比、"
                "归因或需要多步骤工具组合的分析必须使用 COMPLEX_QUERY。用户声称某张采购单当前"
                "处于某状态，不得把该说法当成权威事实；只要问题涉及‘这张/当前采购单’的实际状态，"
                "就必须使用实时工具。若同时询问该状态下接下来怎么处理、适用什么流程或规则，必须"
                "路由到 HYBRID，同时使用实时工具和知识库。数据库主键属于内部字段，绝不能要求"
                "用户提供；用户只需提供采购单号或自然语言描述。明确采购意图应路由 FORM_PREFILL。"
            ),
            {"message": message},
        )
        return output

    async def rewrite_query(self, query: str) -> QueryRewriteOutput:
        output, _, attempts = await self._run(
            ModelPurpose.QUERY_REWRITE,
            QueryRewriteOutput,
            (
                "你是检索 Query Rewrite。保持采购编号、设备名称、角色、时间和否定词不变，只输出"
                "适合知识检索的等价问题。信息充分时可以不改写。"
            ),
            {"query": query},
        )
        if output.changed == (output.rewritten_query.strip() == query.strip()):
            raise StructuredModelRunError(
                "MODEL_REWRITE_CONTRACT_INVALID",
                "Query Rewrite 的 changed 标记与实际文本不一致",
                attempts=attempts,
                retryable=False,
            )
        return output

    async def plan(self, message: str, confirmed_context: dict[str, Any] | None) -> AnalysisPlan:
        output, _, _ = await self._run(
            ModelPurpose.ANALYSIS_PLAN,
            AnalysisPlan,
            (
                "你是采购分析 Planner。只能输出给定 Schema 和其中的只读工具枚举；禁止 SQL、URL、"
                "身份字段和业务写操作。参数只能来自问题或已确认的结构化上下文。聚合统计、趋势、"
                "分组和金额分析只使用 query_purchase_analytics，arguments 必须且只能包含 query；"
                "所有过滤条件必须直接放在 query 内，禁止生成 filters。query 的主要允许字段为 "
                "created_from、created_to、created_by_me、building_ids、device_professions、"
                "device_name、brands、models、supplier_ids、statuses、min_unit_price、"
                "max_unit_price、min_total_price、max_total_price、exclude_blacklisted、"
                "exclude_delayed_suppliers、group_by、aggregations、sort_by、sort_order、"
                "page、page_size。group_by 仅允许 BRAND、BUILDING、SUPPLIER、DEVICE_NAME、"
                "STATUS、MONTH；aggregations 仅允许 COUNT、AVERAGE_UNIT_PRICE、"
                "MEDIAN_UNIT_PRICE、TOTAL_AMOUNT。"
                '正确格式示例："tool":"query_purchase_analytics","arguments":{"query":'
                '{"group_by":"BUILDING","aggregations":["COUNT","TOTAL_AMOUNT"],'
                '"page":1,"page_size":20}}。'
                "get_supplier_performance、get_similar_cases、get_requirement_risk_signals 仅在系统"
                "已经由页面上下文或业务单号解析出内部定位键时使用；不得要求用户提供数据库主键，"
                "也不得编造定位键。query_context 应与分析查询条件一致。"
            ),
            {"message": message, "confirmed_context": confirmed_context},
        )
        return output

    async def compose(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        *,
        allowed_citation_ids: set[str],
    ) -> ComposeOutput:
        output, response, attempts = await self._run(
            ModelPurpose.COMPOSE,
            ComposeOutput,
            (
                "你是采购协同 Compose。只能依据给出的可见证据回答；不得把建议写成事实，不得生成"
                "未提供的引用。citations 仅供界面独立展示来源，answer 正文禁止出现 K1、K2 等"
                "引用编号，也禁止出现 Prompt、Chunk、RAG、Tool、Router、Graph、evidence、"
                "文件路径、行号、内部字段名或‘当前用户可见的知识库证据’等实现措辞。"
                "citations 只能使用 allowed_citation_ids 中的知识库引用；如果该列表"
                "为空，citations 必须为空。Tool 实时事实直接陈述来源，不得伪造 K 编号。正式业务"
                "动作只能说明需要人工确认。不得向用户展示 snake_case 字段名、数据库主键或"
                "英文状态枚举；例如应将 PENDING_PURCHASE 表述为待采购、APPROVED 表述为已通过。"
                "使用普通业务中文，优先按结论、当前情况、下一步操作、注意事项组织；关键动作"
                "加粗，多步骤用编号，避免长段落和机械日志语气。"
            ),
            {
                "question": question,
                "visible_evidence": evidence,
                "allowed_citation_ids": sorted(allowed_citation_ids),
            },
        )
        referenced = {item.citation_id for item in output.citations}
        invalid = referenced - allowed_citation_ids
        if invalid:
            raise StructuredModelRunError(
                "MODEL_CITATION_REFERENCE_INVALID",
                f"模型引用了不可用证据：{', '.join(sorted(invalid))}",
                attempts=attempts,
                retryable=False,
                primary_model=response.primary_model,
                actual_model=response.actual_model,
                fallback_used=response.fallback_used,
                fallback_reason=response.fallback_reason,
            )
        output.answer = self._normalize_public_answer(output.answer)
        self._validate_public_answer(output.answer, attempts, response)
        return output

    async def compose_stream(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        *,
        allowed_citation_ids: set[str],
        answer_delta_handler: Callable[[str], Awaitable[None]],
    ) -> ComposeOutput:
        output, response, attempts = await self._run(
            ModelPurpose.COMPOSE,
            ComposeOutput,
            (
                "你是采购协同 Compose。只能依据给出的可见证据回答；不得把建议写成事实，不得生成"
                "未提供的引用。citations 仅供界面独立展示来源，answer 正文禁止出现 K1、K2 等"
                "引用编号，也禁止出现 Prompt、Chunk、RAG、Tool、Router、Graph、evidence、"
                "文件路径、行号、内部字段名或‘当前用户可见的知识库证据’等实现措辞。"
                "citations 只能使用 allowed_citation_ids 中的知识库引用；如果该列表"
                "为空，citations 必须为空。Tool 实时事实直接陈述来源，不得伪造 K 编号。正式业务"
                "动作只能说明需要人工确认。answer 字段必须是完整、面向业务用户的中文回答。"
                "不得向用户展示 snake_case 字段名、数据库主键或英文状态枚举；例如应将 "
                "PENDING_PURCHASE 表述为待采购、APPROVED 表述为已通过。使用结论、当前情况、"
                "下一步操作、注意事项的清晰结构；关键动作加粗，多步骤用编号，避免机械日志语气。"
            ),
            {
                "question": question,
                "visible_evidence": evidence,
                "allowed_citation_ids": sorted(allowed_citation_ids),
            },
        )
        referenced = {item.citation_id for item in output.citations}
        invalid = referenced - allowed_citation_ids
        if invalid:
            raise StructuredModelRunError(
                "MODEL_CITATION_REFERENCE_INVALID",
                f"模型引用了不可用证据：{', '.join(sorted(invalid))}",
                attempts=attempts,
                retryable=False,
                primary_model=response.primary_model,
                actual_model=response.actual_model,
                fallback_used=response.fallback_used,
                fallback_reason=response.fallback_reason,
            )
        output.answer = self._normalize_public_answer(output.answer)
        self._validate_public_answer(output.answer, attempts, response)
        await answer_delta_handler(output.answer)
        return output

    @staticmethod
    def _normalize_public_answer(answer: str) -> str:
        """Keep model-generated business sections readable in Markdown clients."""
        section_pattern = re.compile(
            r"(^|\s+)(?:#{2,4}\s*)?(结论|当前情况|下一步操作|注意事项)\s*",
            re.MULTILINE,
        )
        normalized = section_pattern.sub(
            lambda match: f"\n\n### {match.group(2)}\n\n",
            answer,
        )
        normalized = re.sub(r"[ \t]+(?=-\s+)", "\n", normalized)
        normalized = re.sub(r"[ \t]+(?=\d+\.\s+)", "\n", normalized)
        return normalized.strip()

    @staticmethod
    def _validate_public_answer(
        answer: str,
        attempts: int,
        response: StructuredModelResponse,
    ) -> None:
        internal_pattern = re.compile(
            r"\[K\d+\]|(?:knowledge|agent_app|app)[/\\][\w./\\-]+\.md(?::\d+)?|"
            r"\b(?:Prompt|Chunk|RAG|Router|Graph|evidence)\b|当前用户可见的知识库证据",
            re.IGNORECASE,
        )
        if internal_pattern.search(answer):
            raise StructuredModelRunError(
                "MODEL_PUBLIC_ANSWER_INVALID",
                "模型回答包含不应向业务用户展示的内部实现信息",
                attempts=attempts,
                retryable=False,
                primary_model=response.primary_model,
                actual_model=response.actual_model,
                fallback_used=response.fallback_used,
                fallback_reason=response.fallback_reason,
            )

    async def review(
        self,
        question: str,
        draft: ComposeOutput,
        evidence: list[dict[str, Any]],
    ) -> ReviewOutput:
        output, _, _ = await self._run(
            ModelPurpose.REVIEW,
            ReviewOutput,
            (
                "你是采购协同 Review。只检查证据缺失、遗漏约束、分析冒充事实、越权、不可见引用、"
                "RAG/Tool 冲突和人工确认需要；不得重新计算后端权限、金额、黑名单、幂等或"
                "状态机规则。"
            ),
            {
                "question": question,
                "draft": draft.model_dump(mode="json"),
                "visible_evidence": evidence,
            },
        )
        return output

    async def _run(
        self,
        purpose: ModelPurpose,
        output_type: type[OutputT],
        system_instruction: str,
        payload: dict[str, Any],
        delta_handler: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[OutputT, StructuredModelResponse, int]:
        request = StructuredModelRequest(
            purpose=purpose,
            trace_id=self._trace_id_context.get(),
            messages=[
                ModelMessage(role="system", content=system_instruction),
                ModelMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                ),
            ],
            response_schema=output_type.model_json_schema(mode="serialization"),
            max_output_tokens=(
                _ROLE_MAX_OUTPUT_TOKENS[purpose] if self.performance_optimizations_enabled else 2000
            ),
            enable_thinking=(
                _ROLE_THINKING[purpose] if self.performance_optimizations_enabled else None
            ),
        )
        output, response, attempts = await self.runner.run(
            request, output_type, delta_handler=delta_handler
        )
        values = dict(self._call_metadata.get() or {})
        values[purpose] = {
            "provider": response.provider,
            "primary_model": response.primary_model or response.model,
            "actual_model": response.actual_model or response.model,
            "fallback_used": response.fallback_used,
            "fallback_reason": response.fallback_reason,
            "attempts": attempts,
            "latency_ms": response.latency_ms,
            "response_headers_ms": response.response_headers_ms,
            "first_token_ms": response.first_token_ms,
            "transport_read_ms": response.transport_read_ms,
            "response_parse_ms": response.response_parse_ms,
            "schema_validation_ms": response.schema_validation_ms,
            "runner_latency_ms": response.runner_latency_ms,
            "retry_overhead_ms": response.retry_overhead_ms,
            "retry_count": max(0, attempts - 1),
            "max_output_tokens": request.max_output_tokens,
            "thinking_enabled": request.enable_thinking,
            "request_id": response.request_id,
        }
        self._call_metadata.set(values)
        return output, response, attempts


class ModelQueryRewriteProvider:
    def __init__(self, roles: StructuredModelRoles) -> None:
        self.roles = roles

    @property
    def cache_identity(self) -> str:
        return f"{self.roles.cache_identity}|query-rewrite-v2"

    async def rewrite(self, query: str) -> str:
        return (await self.roles.rewrite_query(query)).rewritten_query
