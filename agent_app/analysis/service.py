from agent_app.analysis.executor import AnalysisExecutor, AnalysisToolClient
from agent_app.analysis.planner import AnalysisPlanner, DeterministicAnalysisPlanner
from agent_app.analysis.schemas import (
    AnalysisOutput,
    AnalysisTable,
    AnalysisToolName,
)
from agent_app.schemas.analytics import AnalyticsQueryInput


class AnalysisAgentService:
    def __init__(
        self,
        *,
        planner: AnalysisPlanner | None = None,
        executor: AnalysisExecutor | None = None,
    ) -> None:
        self.planner = planner or DeterministicAnalysisPlanner()
        self.executor = executor or AnalysisExecutor()

    async def run(
        self,
        message: str,
        client: AnalysisToolClient,
        *,
        previous_query: AnalyticsQueryInput | None = None,
    ) -> AnalysisOutput:
        plan = await self.planner.create_plan(message, previous_query)
        execution = await self.executor.execute(plan, client, self.planner)
        successful = [step for step in execution.steps if step.success]
        warnings = [
            f"{step.step_id}: {step.message}" for step in execution.steps if not step.success
        ]
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
                    if primary.tool is AnalysisToolName.GET_SIMILAR_CASES:
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
        )

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
