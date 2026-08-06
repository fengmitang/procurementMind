import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue, ValidationError

from agent_app.analysis.planner import DeterministicAnalysisPlanner
from agent_app.analysis.schemas import AnalysisPlanStep
from agent_app.evaluation.runner import EvaluationRunner
from agent_app.evaluation.schemas import EvaluationCase, EvaluationReport
from agent_app.graph.router import FirstVersionRouter
from agent_app.graph.schemas import RouteType


@dataclass(frozen=True)
class DeterministicCaseSets:
    router: list[EvaluationCase]
    tool: list[EvaluationCase]
    analysis: list[EvaluationCase]
    risk: list[EvaluationCase]


def load_deterministic_cases(fixtures_dir: Path) -> DeterministicCaseSets:
    router = _load_evaluation_cases(fixtures_dir / "router_evaluation_v0.1.json")
    tool = _load_evaluation_cases(fixtures_dir / "tool_security_evaluation_v0.1.json")
    analysis_source = _load_json(fixtures_dir / "analysis_evaluation_v0.1.json")
    risk_source = _load_json(fixtures_dir / "risk_evaluation_v0.1.json")
    analysis: list[EvaluationCase] = []
    for item in analysis_source:
        expected_arguments = item.get("expected_arguments")
        if expected_arguments is None:
            expected_arguments = {"query": item["expected_query"]}
        analysis.append(
            EvaluationCase(
                case_id=item["id"],
                category="analysis-planner",
                input={"message": item["message"]},
                expected_subset={
                    "tool": item["expected_tool"],
                    "arguments": expected_arguments,
                },
            )
        )
    risk = [
        EvaluationCase(
            case_id=item["case_id"],
            category="risk-contract",
            input={
                "expected_risk_codes": item["expected_risk_codes"],
                "forbidden_risk_codes": item["forbidden_risk_codes"],
            },
            expected_subset={
                "valid": True,
                "expected_count": len(item["expected_risk_codes"]),
                "forbidden_count": len(item["forbidden_risk_codes"]),
            },
        )
        for item in risk_source
    ]
    return DeterministicCaseSets(router=router, tool=tool, analysis=analysis, risk=risk)


def _load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    return [EvaluationCase.model_validate(item) for item in _load_json(path)]


def _load_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"评测文件必须是 JSON 数组：{path}")
    return data


class RouterEvaluationSubject:
    async def execute(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        message = str(payload["message"])
        router = FirstVersionRouter()
        route = router.classify(message)
        requirement_id = None
        if route in {
            RouteType.REALTIME_BUSINESS,
            RouteType.HYBRID,
            RouteType.RISK_INVESTIGATION,
        }:
            requirement_id = router.extract_requirement_id(message)
        return {"route": route.value, "requirement_id": requirement_id}


class ToolContractEvaluationSubject:
    async def execute(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            AnalysisPlanStep.model_validate(
                {
                    "step_id": "evaluation_step",
                    "objective": "验证工具参数契约",
                    "tool": payload["tool"],
                    "arguments": payload["arguments"],
                }
            )
        except (ValidationError, ValueError):
            return {"accepted": False, "error_code": "TOOL_ARGUMENTS_INVALID"}
        return {"accepted": True, "error_code": None}


class AnalysisPlannerEvaluationSubject:
    def __init__(self) -> None:
        self.planner = DeterministicAnalysisPlanner()

    async def execute(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        plan = await self.planner.create_plan(str(payload["message"]))
        first_step = plan.steps[0]
        return {
            "tool": first_step.tool.value,
            "arguments": first_step.arguments,
        }


class RiskContractEvaluationSubject:
    async def execute(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        expected = {str(value) for value in payload.get("expected_risk_codes", [])}
        forbidden = {str(value) for value in payload.get("forbidden_risk_codes", [])}
        return {
            "valid": not bool(expected & forbidden),
            "expected_count": len(expected),
            "forbidden_count": len(forbidden),
        }


async def run_deterministic_suites(
    *,
    router_cases: list[EvaluationCase],
    tool_cases: list[EvaluationCase],
    analysis_cases: list[EvaluationCase],
    risk_cases: list[EvaluationCase],
) -> list[EvaluationReport]:
    runner = EvaluationRunner()
    return [
        await runner.run("router", router_cases, RouterEvaluationSubject()),
        await runner.run("tool-security", tool_cases, ToolContractEvaluationSubject()),
        await runner.run("analysis-planner", analysis_cases, AnalysisPlannerEvaluationSubject()),
        await runner.run("risk-contract", risk_cases, RiskContractEvaluationSubject()),
    ]
