import asyncio
import time
from typing import Protocol

from agent_app.investigation.reviewer import ProgramEvidenceReviewer
from agent_app.investigation.schemas import (
    EvidenceStatus,
    InvestigationEvidence,
    InvestigationEvidenceKind,
    RiskInvestigationOutput,
    RiskSummaryItem,
)
from agent_app.mcp.client import MCPClientError
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.rag.schemas import RetrievalFilters, RetrievalResult


class InvestigationToolClient(Protocol):
    async def call_tool(
        self,
        name: str,
        arguments: dict | None = None,
    ) -> MCPToolResponse: ...


class InvestigationKnowledgeRetriever(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult: ...


class RiskInvestigationService:
    def __init__(
        self,
        reviewer: ProgramEvidenceReviewer | None = None,
        *,
        max_tool_calls: int = 8,
    ) -> None:
        self.reviewer = reviewer or ProgramEvidenceReviewer()
        self.max_tool_calls = max_tool_calls

    async def run(
        self,
        requirement_id: int,
        client: InvestigationToolClient,
        *,
        knowledge_retriever: InvestigationKnowledgeRetriever | None = None,
        allowed_roles: list[str] | None = None,
        question: str | None = None,
        trace_id: str | None = None,
    ) -> RiskInvestigationOutput:
        risk_evidence = await self._call(
            "risk_signals",
            InvestigationEvidenceKind.RISK_SIGNALS,
            "get_requirement_risk_signals",
            {"requirement_id": requirement_id},
            client,
        )
        evidence = [risk_evidence]
        if risk_evidence.status is not EvidenceStatus.SUCCESS:
            review = self.reviewer.review([], evidence)
            return RiskInvestigationOutput(
                requirement_id=requirement_id,
                answer="后端风险信号不可用，调查已停止，本次不会猜测风险。",
                summary_items=[],
                evidence=evidence,
                review=review,
                complete=False,
                warnings=[risk_evidence.message or "风险信号查询失败"],
            )

        if self.max_tool_calls < 2:
            knowledge = InvestigationEvidence(
                evidence_id="tool_budget",
                kind=InvestigationEvidenceKind.REQUIREMENT,
                status=EvidenceStatus.UNAVAILABLE,
                source="langgraph://tool-budget",
                code="GRAPH_TOOL_CALL_LIMIT",
                message="工具预算不足，未执行风险补查",
            )
            evidence.append(knowledge)
            items = self._build_summary(risk_evidence, evidence)
            review = self.reviewer.review(items, evidence)
            return RiskInvestigationOutput(
                requirement_id=requirement_id,
                answer="已读取后端风险信号，但工具预算不足，未完成补查。",
                summary_items=items,
                evidence=evidence,
                review=review,
                complete=False,
                warnings=["工具预算不足，未执行风险补查"],
            )
        requirement = await self._call(
            "requirement",
            InvestigationEvidenceKind.REQUIREMENT,
            "get_purchase_request",
            {"requirement_id": requirement_id},
            client,
        )
        evidence.append(requirement)
        follow_ups = self._follow_up_calls(requirement_id, requirement)
        available_follow_ups = max(0, self.max_tool_calls - 2)
        skipped_follow_ups = follow_ups[available_follow_ups:]
        follow_ups = follow_ups[:available_follow_ups]
        follow_up_evidence = await asyncio.gather(
            *(
                self._call(evidence_id, kind, tool, arguments, client)
                for evidence_id, kind, tool, arguments in follow_ups
            )
        )
        evidence.extend(follow_up_evidence)
        evidence.extend(
            InvestigationEvidence(
                evidence_id=evidence_id,
                kind=kind,
                status=EvidenceStatus.UNAVAILABLE,
                source="langgraph://tool-budget",
                tool_name=None,
                arguments=arguments,
                code="GRAPH_TOOL_CALL_LIMIT",
                message=f"工具预算不足，未执行 {tool}",
            )
            for evidence_id, kind, tool, arguments in skipped_follow_ups
        )
        knowledge_evidence = await self._retrieve_knowledge(
            requirement_id,
            requirement,
            risk_evidence,
            knowledge_retriever=knowledge_retriever,
            allowed_roles=allowed_roles or [],
            question=question,
            trace_id=trace_id,
        )
        evidence.append(knowledge_evidence)
        items = self._build_summary(risk_evidence, evidence)
        review = self.reviewer.review(items, evidence)
        failed = [item for item in evidence if item.status is EvidenceStatus.FAILED]
        unavailable = [item for item in evidence if item.status is EvidenceStatus.UNAVAILABLE]
        complete = not failed and not unavailable and review.passed
        warnings = [
            item.message or item.code or "证据不可用"
            for item in evidence
            if item.status is not EvidenceStatus.SUCCESS
        ]
        matched_count = len(items)
        answer = (
            f"后端命中 {matched_count} 项确定性风险；已补查可用业务证据。"
            if matched_count
            else "后端未命中确定性风险；这不代表审批结论。"
        )
        if unavailable:
            answer += "未检索到可确认的适用制度依据，制度证据标记为信息不足。"
        if failed:
            answer += f"另有 {len(failed)} 项业务证据查询失败。"
        answer += "风险调查结果不替代人工审批结论。"
        return RiskInvestigationOutput(
            requirement_id=requirement_id,
            answer=answer,
            summary_items=items,
            evidence=evidence,
            review=review,
            complete=complete,
            knowledge_evidence_available=(knowledge_evidence.status is EvidenceStatus.SUCCESS),
            warnings=warnings,
        )

    @staticmethod
    async def _retrieve_knowledge(
        requirement_id: int,
        requirement: InvestigationEvidence,
        risk_evidence: InvestigationEvidence,
        *,
        knowledge_retriever: InvestigationKnowledgeRetriever | None,
        allowed_roles: list[str],
        question: str | None,
        trace_id: str | None,
    ) -> InvestigationEvidence:
        source = "rag://procurement-rules"
        if knowledge_retriever is None:
            return InvestigationEvidence(
                evidence_id="knowledge_rule",
                kind=InvestigationEvidenceKind.KNOWLEDGE_RULE,
                status=EvidenceStatus.UNAVAILABLE,
                source=source,
                code="RAG_NOT_CONFIGURED",
                message="知识检索服务未配置，无法核对适用制度依据",
            )
        if not allowed_roles:
            return InvestigationEvidence(
                evidence_id="knowledge_rule",
                kind=InvestigationEvidenceKind.KNOWLEDGE_RULE,
                status=EvidenceStatus.UNAVAILABLE,
                source=source,
                code="KNOWLEDGE_ROLE_REQUIRED",
                message="当前用户没有可用于知识权限过滤的角色",
            )
        query = RiskInvestigationService._knowledge_query(
            requirement_id, requirement, risk_evidence, question
        )
        started = time.perf_counter()
        try:
            result = await knowledge_retriever.retrieve(
                query,
                filters=RetrievalFilters(
                    allowed_roles=allowed_roles,
                    chunk_types=["risk", "rule", "section", "faq"],
                ),
                trace_id=trace_id,
            )
        except Exception:
            return InvestigationEvidence(
                evidence_id="knowledge_rule",
                kind=InvestigationEvidenceKind.KNOWLEDGE_RULE,
                status=EvidenceStatus.UNAVAILABLE,
                source=source,
                code="RAG_RETRIEVAL_FAILURE",
                message="制度知识检索失败，未使用未经确认的制度依据",
                duration_ms=RiskInvestigationService._elapsed_ms(started),
            )
        if not result.answerable or not result.evidences:
            return InvestigationEvidence(
                evidence_id="knowledge_rule",
                kind=InvestigationEvidenceKind.KNOWLEDGE_RULE,
                status=EvidenceStatus.UNAVAILABLE,
                source=source,
                code="RAG_EVIDENCE_INSUFFICIENT",
                message=result.abstention_reason or "未检索到可确认的适用制度依据",
                trace_id=result.trace.trace_id,
                duration_ms=RiskInvestigationService._elapsed_ms(started),
            )
        return InvestigationEvidence(
            evidence_id="knowledge_rule",
            kind=InvestigationEvidenceKind.KNOWLEDGE_RULE,
            status=EvidenceStatus.SUCCESS,
            source=source,
            data={
                "query": query,
                "citations": [item.citation.model_dump(mode="json") for item in result.evidences],
                "passages": [item.context_content for item in result.evidences],
            },
            trace_id=result.trace.trace_id,
            duration_ms=RiskInvestigationService._elapsed_ms(started),
        )

    @staticmethod
    def _knowledge_query(
        requirement_id: int,
        requirement: InvestigationEvidence,
        risk_evidence: InvestigationEvidence,
        question: str | None,
    ) -> str:
        parts = [question or f"采购申请 {requirement_id} 风险调查适用哪些制度和人工核查要求"]
        if isinstance(requirement.data, dict):
            applicant = requirement.data.get("applicant_fields")
            if isinstance(applicant, dict):
                for field in ("device_profession", "device_name"):
                    value = applicant.get(field)
                    if isinstance(value, str) and value:
                        parts.append(value)
        if isinstance(risk_evidence.data, dict):
            risk_types = [
                str(signal["risk_type"])
                for signal in risk_evidence.data.get("signals", [])
                if isinstance(signal, dict)
                and signal.get("matched") is True
                and signal.get("risk_type")
            ]
            parts.extend(risk_types)
        parts.append("采购制度 风险核查 人工审批")
        return " ".join(dict.fromkeys(parts))

    @staticmethod
    def _follow_up_calls(
        requirement_id: int,
        requirement: InvestigationEvidence,
    ) -> list[tuple[str, InvestigationEvidenceKind, str, dict]]:
        calls: list[tuple[str, InvestigationEvidenceKind, str, dict]] = [
            (
                "similar_cases",
                InvestigationEvidenceKind.SIMILAR_CASES,
                "get_similar_cases",
                {"requirement_id": requirement_id, "limit": 10},
            )
        ]
        if requirement.status is not EvidenceStatus.SUCCESS or not isinstance(
            requirement.data, dict
        ):
            return calls
        data = requirement.data
        applicant = data.get("applicant_fields")
        if isinstance(applicant, dict):
            query: dict = {
                "aggregations": [
                    "COUNT",
                    "AVERAGE_UNIT_PRICE",
                    "MEDIAN_UNIT_PRICE",
                    "TOTAL_AMOUNT",
                ],
                "page_size": 20,
            }
            if applicant.get("device_profession"):
                query["device_professions"] = [applicant["device_profession"]]
            if applicant.get("device_name"):
                query["device_name"] = applicant["device_name"]
            if applicant.get("brand"):
                query["brands"] = [applicant["brand"]]
            calls.append(
                (
                    "historical_price",
                    InvestigationEvidenceKind.HISTORICAL_PRICE,
                    "query_purchase_analytics",
                    {"query": query},
                )
            )
        supplier_id = RiskInvestigationService._supplier_id(data)
        if supplier_id:
            calls.append(
                (
                    "supplier_performance",
                    InvestigationEvidenceKind.SUPPLIER_PERFORMANCE,
                    "get_supplier_performance",
                    {"supplier_id": supplier_id},
                )
            )
        return calls

    @staticmethod
    def _supplier_id(requirement: dict) -> int | None:
        execution = requirement.get("purchase_execution")
        if isinstance(execution, dict) and isinstance(execution.get("supplier_id"), int):
            return execution["supplier_id"]
        reviews = requirement.get("review_records")
        if isinstance(reviews, list):
            for review in reversed(reviews):
                if isinstance(review, dict) and isinstance(review.get("proposed_supplier_id"), int):
                    return review["proposed_supplier_id"]
        return None

    @staticmethod
    def _build_summary(
        risk_evidence: InvestigationEvidence,
        evidence: list[InvestigationEvidence],
    ) -> list[RiskSummaryItem]:
        if not isinstance(risk_evidence.data, dict):
            return []
        sources = [item.source for item in evidence if item.status is EvidenceStatus.SUCCESS]
        knowledge_available = any(
            item.kind is InvestigationEvidenceKind.KNOWLEDGE_RULE
            and item.status is EvidenceStatus.SUCCESS
            for item in evidence
        )
        items: list[RiskSummaryItem] = []
        for signal in risk_evidence.data.get("signals", []):
            if not isinstance(signal, dict) or signal.get("matched") is not True:
                continue
            risk_code = str(signal.get("risk_code", "UNKNOWN"))
            items.append(
                RiskSummaryItem(
                    risk_code=risk_code,
                    risk_type=str(signal.get("risk_type", risk_code)),
                    risk_level=str(signal.get("risk_level", "INFO")),
                    backend_rule_matched=True,
                    facts=signal.get("facts", {}),
                    metrics=signal.get("metrics", {}),
                    related_record_ids=signal.get("related_record_ids", []),
                    data_sources=sources,
                    applicable_rule=signal.get("threshold", {}),
                    possible_causes=[RiskInvestigationService._possible_cause(risk_code)],
                    information_complete=knowledge_available,
                    information_gaps=(
                        [] if knowledge_available else ["缺少真实采购制度和适用条款证据"]
                    ),
                    human_checks=[RiskInvestigationService._human_check(risk_code)],
                )
            )
        return items

    @staticmethod
    def _possible_cause(risk_code: str) -> str:
        causes = {
            "DUPLICATE_APPLICATION": "可能存在需求重复、拆分或合理的追加采购，原因尚需人工核实",
            "DUPLICATE_PURCHASE": "可能存在需求重复、拆分或合理的追加采购，原因尚需人工核实",
            "PRICE_DEVIATION": "可能受配置差异、采购时点或市场价格变化影响，原因尚需人工核实",
            "QUANTITY_DEVIATION": "可能存在需求变更、分批入库或登记差异，原因尚需人工核实",
            "QUANTITY_ANOMALY": "可能存在需求变更、分批入库或登记差异，原因尚需人工核实",
            "SUPPLIER_BLACKLIST": "供应商命中当前有效黑名单，具体处置需依据正式制度人工确认",
            "DELIVERY_DELAY": "可能受供货、物流或验收安排影响，原因尚需人工核实",
            "LONG_PENDING_RECEIPT": "可能存在未到货、未登记或分批入库，原因尚需人工核实",
            "SIMILAR_APPLICATION": "存在规则相似的历史申请，不等同于重复采购",
        }
        return causes.get(risk_code, "后端规则已命中，具体原因尚需人工核实")

    @staticmethod
    def _human_check(risk_code: str) -> str:
        checks = {
            "DUPLICATE_APPLICATION": "核对相似申请是否属于追加、替换或重复需求",
            "PRICE_DEVIATION": "核对设备配置、报价时间和询价依据",
            "QUANTITY_DEVIATION": "核对申请数量、到货批次和入库记录",
            "QUANTITY_ANOMALY": "核对申请数量、到货批次和入库记录",
            "SUPPLIER_BLACKLIST": "核对黑名单有效期、原因和正式处置规则",
            "DELIVERY_DELAY": "核对预计到货日期、实际到货和延期说明",
            "LONG_PENDING_RECEIPT": "核对采购执行、物流和未入库原因",
            "DUPLICATE_PURCHASE": "核对相似申请是否属于追加、替换或重复需求",
            "SIMILAR_APPLICATION": "比较相似申请的楼宇、设备、数量和用途",
        }
        return checks.get(risk_code, "核对原始申请、业务记录和适用制度")

    @staticmethod
    async def _call(
        evidence_id: str,
        kind: InvestigationEvidenceKind,
        tool_name: str,
        arguments: dict,
        client: InvestigationToolClient,
    ) -> InvestigationEvidence:
        started = time.perf_counter()
        try:
            response = await client.call_tool(tool_name, arguments)
        except MCPClientError as exc:
            return RiskInvestigationService._failed_evidence(
                evidence_id,
                kind,
                tool_name,
                arguments,
                exc.code,
                exc.message,
                started,
            )
        except Exception:
            return RiskInvestigationService._failed_evidence(
                evidence_id,
                kind,
                tool_name,
                arguments,
                "MCP_UNEXPECTED_FAILURE",
                "证据工具执行发生未预期故障",
                started,
            )
        return InvestigationEvidence(
            evidence_id=evidence_id,
            kind=kind,
            status=EvidenceStatus.SUCCESS if response.success else EvidenceStatus.FAILED,
            source=response.source,
            tool_name=tool_name,
            arguments=arguments,
            data=response.data,
            code=None if response.success else response.code,
            message=None if response.success else response.message,
            trace_id=response.trace_id,
            duration_ms=RiskInvestigationService._elapsed_ms(started),
        )

    @staticmethod
    def _failed_evidence(
        evidence_id: str,
        kind: InvestigationEvidenceKind,
        tool_name: str,
        arguments: dict,
        code: str,
        message: str,
        started: float,
    ) -> InvestigationEvidence:
        return InvestigationEvidence(
            evidence_id=evidence_id,
            kind=kind,
            status=EvidenceStatus.FAILED,
            source=f"mcp://{tool_name}",
            tool_name=tool_name,
            arguments=arguments,
            code=code,
            message=message,
            duration_ms=RiskInvestigationService._elapsed_ms(started),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
