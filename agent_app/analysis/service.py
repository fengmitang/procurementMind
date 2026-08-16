from typing import Protocol

from agent_app.analysis.executor import AnalysisExecutor, AnalysisToolClient
from agent_app.analysis.planner import AnalysisPlanner, DeterministicAnalysisPlanner
from agent_app.analysis.schemas import (
    AnalysisOutput,
    AnalysisPlan,
    AnalysisPlanStep,
    AnalysisTable,
    AnalysisToolName,
)
from agent_app.device_terms.schemas import (
    DeviceTermLookupResult,
    DeviceTermLookupStatus,
)
from agent_app.domain.device_catalog import get_device_catalog
from agent_app.schemas.analytics import AnalyticsQueryInput
from app.schemas.procurement import DeviceType


class DeviceTermSearchProtocol(Protocol):
    top_k: int

    async def lookup(
        self,
        query_term: str,
        device_profession: DeviceType,
    ) -> DeviceTermLookupResult: ...


class AnalysisAgentService:
    def __init__(
        self,
        *,
        planner: AnalysisPlanner | None = None,
        executor: AnalysisExecutor | None = None,
        device_term_search: DeviceTermSearchProtocol | None = None,
    ) -> None:
        self.planner = planner or DeterministicAnalysisPlanner()
        self.executor = executor or AnalysisExecutor()
        self.device_term_search = device_term_search

    def set_device_term_search(self, service: DeviceTermSearchProtocol) -> None:
        self.device_term_search = service

    async def run(
        self,
        message: str,
        client: AnalysisToolClient,
        *,
        previous_query: AnalyticsQueryInput | None = None,
        prepared_plan: AnalysisPlan | None = None,
    ) -> AnalysisOutput:
        plan = prepared_plan or await self.planner.create_plan(message, previous_query)
        plan, device_term_lookup = await self._enrich_device_term_query(plan)
        if (
            device_term_lookup is not None
            and device_term_lookup.status is DeviceTermLookupStatus.CLASSIFICATION_REQUIRED
        ):
            return AnalysisOutput(
                answer=(
                    "设备名称可能对应多个设备类型，暂时不能安全执行历史采购查询。"
                    "请补充设备类型、所属系统或电压等级后再查询。"
                ),
                plan=plan,
                effective_query=plan.query_context,
                step_results=[],
                warnings=[device_term_lookup.message or "设备类型不足以确定"],
                device_term_lookup=device_term_lookup,
            )
        execution = await self.executor.execute(plan, client, self.planner)
        successful = [step for step in execution.steps if step.success]
        warnings = [
            f"{step.step_id}: {step.message}" for step in execution.steps if not step.success
        ]
        if (
            device_term_lookup is not None
            and device_term_lookup.fallback_triggered
            and device_term_lookup.message
        ):
            warnings.append(device_term_lookup.message)
        datasets = {step.step_id: step.data for step in successful if step.data is not None}
        summary: dict = {}
        groups: list[dict] = []
        candidates: list[dict] = []
        table = None
        effective_query = plan.query_context
        if successful:
            primary = successful[-1]
            data = primary.data if isinstance(primary.data, dict) else {}
            if primary.tool is AnalysisToolName.QUERY_PURCHASE_ANALYTICS:
                summary = data.get("summary", {})
                groups = data.get("groups", [])
                items = data.get("items", [])
                columns = list(items[0]) if items and isinstance(items[0], dict) else []
                table = AnalysisTable(columns=columns, rows=items, total=data.get("total"))
                backend_query = data.get("effective_query")
                if isinstance(backend_query, dict):
                    effective_query = AnalyticsQueryInput.model_validate(
                        {
                            key: value
                            for key, value in backend_query.items()
                            if key in AnalyticsQueryInput.model_fields
                        }
                    )
            elif primary.tool is AnalysisToolName.GET_SUPPLIER_PERFORMANCE:
                summary = data
            else:
                items = data.get("items", data.get("signals", []))
                if isinstance(items, list):
                    columns = list(items[0]) if items and isinstance(items[0], dict) else []
                    table = AnalysisTable(columns=columns, rows=items, total=len(items))
                    if primary.tool in {
                        AnalysisToolName.GET_SIMILAR_CASES,
                        AnalysisToolName.RECOMMEND_SUPPLIERS,
                    }:
                        candidates = items
                summary = {
                    key: value for key, value in data.items() if key not in {"items", "signals"}
                }
        answer = self._answer(
            execution.successful_steps, execution.failed_steps, summary, groups, table
        )
        return AnalysisOutput(
            answer=answer,
            plan=execution.plan,
            effective_query=effective_query,
            datasets=datasets,
            summary=summary,
            groups=groups,
            candidates=candidates,
            table=table,
            step_results=execution.steps,
            warnings=warnings,
            partial_success=execution.partial_success,
            device_term_lookup=device_term_lookup,
        )

    async def _enrich_device_term_query(
        self,
        plan: AnalysisPlan,
    ) -> tuple[AnalysisPlan, DeviceTermLookupResult | None]:
        query = plan.query_context
        if query is None:
            query_step = next(
                (
                    step
                    for step in plan.steps
                    if step.tool is AnalysisToolName.QUERY_PURCHASE_ANALYTICS
                ),
                None,
            )
            if query_step is not None:
                raw_query = query_step.arguments.get("query")
                if isinstance(raw_query, dict):
                    query = AnalyticsQueryInput.model_validate(raw_query)
                    plan = self._replace_query(plan, query)
        if query is None:
            return plan, None
        if query.device_names:
            query = query.model_copy(update={"device_names": []})
            plan = self._replace_query(plan, query)
        if not query.device_name:
            return plan, None
        if len(query.device_professions) != 1:
            if get_device_catalog().ambiguous_matches(query.device_name):
                return plan, DeviceTermLookupResult(
                    status=DeviceTermLookupStatus.CLASSIFICATION_REQUIRED,
                    query_term=query.device_name,
                    top_k=self.device_term_search.top_k if self.device_term_search else 5,
                    message="该设备名称属于歧义术语，必须先确认 device_profession",
                )
            return plan, None
        profession = query.device_professions[0]
        if self.device_term_search is None:
            return plan, DeviceTermLookupResult(
                status=DeviceTermLookupStatus.SKIPPED,
                query_term=query.device_name,
                device_profession=profession,
                top_k=5,
                fallback_triggered=True,
                error_code="DEVICE_TERM_SEARCH_NOT_CONFIGURED",
                message="设备术语语义检索未配置，保留原始 Backend 查询",
            )
        lookup = await self.device_term_search.lookup(query.device_name, profession)
        if lookup.selected_names:
            query = query.model_copy(update={"device_names": lookup.selected_names})
            plan = self._replace_query(plan, query)
        return plan, lookup

    @staticmethod
    def _replace_query(plan: AnalysisPlan, query: AnalyticsQueryInput) -> AnalysisPlan:
        steps = []
        for step in plan.steps:
            if step.tool is AnalysisToolName.QUERY_PURCHASE_ANALYTICS:
                steps.append(
                    AnalysisPlanStep.model_validate(
                        {
                            **step.model_dump(mode="python"),
                            "arguments": {"query": query.model_dump(mode="json")},
                        }
                    )
                )
            else:
                steps.append(step)
        return plan.model_copy(update={"query_context": query, "steps": steps})

    @staticmethod
    def _answer(
        successful: int, failed: int, summary: dict, groups: list, table: AnalysisTable | None
    ) -> str:
        if not successful:
            return "分析工具未返回可确认的数据，本次不会猜测结果。"
        parts = ["已按采购后端授权范围完成分析。"]
        if summary:
            values = "，".join(
                f"{key}={value}" for key, value in summary.items() if value is not None
            )
            if values:
                parts.append(f"汇总：{values}。")
        if groups:
            parts.append(f"返回 {len(groups)} 个分组。")
        if table:
            parts.append(
                f"返回 {table.total if table.total is not None else len(table.rows)} 条记录。"
            )
        if failed:
            parts.append(f"另有 {failed} 个步骤失败，结果为部分成功。")
        return "".join(parts)
