import asyncio
import time
from typing import Protocol

from agent_app.analysis.planner import AnalysisPlanner
from agent_app.analysis.schemas import (
    AnalysisExecutionResult,
    AnalysisPlan,
    AnalysisPlanStep,
    AnalysisStepResult,
)
from agent_app.mcp.client import MCPClientError
from agent_app.mcp.schemas import MCPToolResponse


class AnalysisToolClient(Protocol):
    async def call_tool(
        self,
        name: str,
        arguments: dict | None = None,
    ) -> MCPToolResponse: ...


class AnalysisExecutor:
    def __init__(self, *, max_tool_calls: int = 8) -> None:
        self.max_tool_calls = max_tool_calls

    async def execute(
        self,
        plan: AnalysisPlan,
        client: AnalysisToolClient,
        planner: AnalysisPlanner,
    ) -> AnalysisExecutionResult:
        results: list[AnalysisStepResult] = []
        completed_ids: set[str] = set()
        active_plan = plan
        await self._execute_plan(active_plan, client, results, completed_ids)
        if any(not item.success for item in results):
            revised = await planner.revise_plan(active_plan, results)
            if revised is not None:
                active_plan = revised
                await self._execute_plan(active_plan, client, results, completed_ids)
        successful = sum(item.success for item in results)
        failed = len(results) - successful
        return AnalysisExecutionResult(
            plan=active_plan,
            steps=results,
            successful_steps=successful,
            failed_steps=failed,
            partial_success=successful > 0 and failed > 0,
        )

    async def _execute_plan(
        self,
        plan: AnalysisPlan,
        client: AnalysisToolClient,
        results: list[AnalysisStepResult],
        completed_ids: set[str],
    ) -> None:
        pending = [step for step in plan.steps if step.step_id not in completed_ids]
        while pending and len(results) < self.max_tool_calls:
            ready = [
                step
                for step in pending
                if all(dependency in completed_ids for dependency in step.depends_on)
            ]
            if not ready:
                break
            parallel = [step for step in ready if step.independent]
            batch = parallel if len(parallel) > 1 else [ready[0]]
            batch_results = await asyncio.gather(
                *(self._call(step, client) for step in batch),
            )
            results.extend(batch_results)
            completed_ids.update(item.step_id for item in batch_results if item.success)
            pending = [
                step for step in pending if step.step_id not in {item.step_id for item in batch}
            ]

    @staticmethod
    async def _call(
        step: AnalysisPlanStep,
        client: AnalysisToolClient,
    ) -> AnalysisStepResult:
        started = time.perf_counter()
        try:
            response = await client.call_tool(step.tool.value, step.arguments)
        except MCPClientError as exc:
            return AnalysisStepResult(
                step_id=step.step_id,
                tool=step.tool,
                arguments=step.arguments,
                success=False,
                code=exc.code,
                message=exc.message,
                source=f"mcp://{step.tool.value}",
                trace_id="unknown",
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            )
        except Exception:
            return AnalysisStepResult(
                step_id=step.step_id,
                tool=step.tool,
                arguments=step.arguments,
                success=False,
                code="MCP_UNEXPECTED_FAILURE",
                message="分析工具执行发生未预期故障",
                source=f"mcp://{step.tool.value}",
                trace_id="unknown",
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            )
        return AnalysisStepResult(
            step_id=step.step_id,
            tool=step.tool,
            arguments=step.arguments,
            success=response.success,
            code=response.code,
            message=response.message,
            source=response.source,
            trace_id=response.trace_id,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            data=response.data,
        )
