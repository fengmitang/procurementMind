import json
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


class StructuredModelRoles:
    """Provider-neutral structured entry points for the five model roles."""

    def __init__(self, runner: StructuredModelRunner, trace_id: str) -> None:
        self.runner = runner
        self.trace_id = trace_id

    async def route(self, message: str) -> RouterOutput:
        output, _, _ = await self._run(
            ModelPurpose.ROUTER,
            RouterOutput,
            (
                "你是采购协同 Router。只按 Schema 分类，不回答问题。实时状态、处理人、价格、"
                "采购记录、供应商、黑名单和统计必须标记需要实时工具；制度和操作规则需要知识库。"
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
                "身份字段和业务写操作。参数只能来自问题或已确认的结构化上下文。"
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
        output, _, attempts = await self._run(
            ModelPurpose.COMPOSE,
            ComposeOutput,
            (
                "你是采购协同 Compose。只能依据给出的可见证据回答；不得把建议写成事实，不得生成"
                "未提供的引用。正式业务动作只能说明需要人工确认。"
            ),
            {"question": question, "visible_evidence": evidence},
        )
        referenced = {item.citation_id for item in output.citations}
        invalid = referenced - allowed_citation_ids
        if invalid:
            raise StructuredModelRunError(
                "MODEL_CITATION_REFERENCE_INVALID",
                f"模型引用了不可用证据：{', '.join(sorted(invalid))}",
                attempts=attempts,
                retryable=False,
            )
        return output

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
    ) -> tuple[OutputT, StructuredModelResponse, int]:
        request = StructuredModelRequest(
            purpose=purpose,
            trace_id=self.trace_id,
            messages=[
                ModelMessage(role="system", content=system_instruction),
                ModelMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                ),
            ],
            response_schema=output_type.model_json_schema(mode="serialization"),
        )
        return await self.runner.run(request, output_type)


class ModelQueryRewriteProvider:
    def __init__(self, roles: StructuredModelRoles) -> None:
        self.roles = roles

    async def rewrite(self, query: str) -> str:
        return (await self.roles.rewrite_query(query)).rewritten_query
