from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent_app.schemas.analytics import AnalyticsQueryInput


class AnalysisToolName(StrEnum):
    QUERY_PURCHASE_ANALYTICS = "query_purchase_analytics"
    GET_SUPPLIER_PERFORMANCE = "get_supplier_performance"
    GET_SIMILAR_CASES = "get_similar_cases"
    GET_REQUIREMENT_RISK_SIGNALS = "get_requirement_risk_signals"
    RECOMMEND_SUPPLIERS = "recommend_suppliers"


class AnalysisPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    objective: str = Field(min_length=1, max_length=300)
    tool: AnalysisToolName
    arguments: dict[str, JsonValue]
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    independent: bool = False

    @model_validator(mode="after")
    def validate_tool_arguments(self) -> "AnalysisPlanStep":
        allowed_keys = {
            AnalysisToolName.QUERY_PURCHASE_ANALYTICS: {"query"},
            AnalysisToolName.GET_SUPPLIER_PERFORMANCE: {
                "supplier_id",
                "created_from",
                "created_to",
            },
            AnalysisToolName.GET_SIMILAR_CASES: {"requirement_id", "limit"},
            AnalysisToolName.GET_REQUIREMENT_RISK_SIGNALS: {"requirement_id"},
            AnalysisToolName.RECOMMEND_SUPPLIERS: {"requirement_id", "limit"},
        }[self.tool]
        if not set(self.arguments).issubset(allowed_keys):
            raise ValueError(f"工具 {self.tool.value} 包含非白名单参数")
        if self.tool is AnalysisToolName.QUERY_PURCHASE_ANALYTICS:
            if set(self.arguments) != {"query"} or not isinstance(self.arguments["query"], dict):
                raise ValueError("分析查询工具必须包含结构化 query 参数")
            AnalyticsQueryInput.model_validate(self.arguments["query"])
        else:
            id_field = (
                "supplier_id"
                if self.tool is AnalysisToolName.GET_SUPPLIER_PERFORMANCE
                else "requirement_id"
            )
            value = self.arguments.get(id_field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"工具 {self.tool.value} 必须包含正整数 {id_field}")
        limit = self.arguments.get("limit")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20
        ):
            raise ValueError("相似案例 limit 必须在 1 到 20 之间")
        return self


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=1000)
    steps: list[AnalysisPlanStep] = Field(min_length=1, max_length=8)
    termination_condition: str = Field(min_length=1, max_length=300)
    revision_count: int = Field(default=0, ge=0, le=1)
    query_context: AnalyticsQueryInput | None = None

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> "AnalysisPlan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("计划步骤 ID 不允许重复")
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError("步骤不能依赖自身")
            if any(dependency not in seen for dependency in step.depends_on):
                raise ValueError("步骤只能依赖计划中更早的步骤")
            seen.add(step.step_id)
        return self


class AnalysisStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    tool: AnalysisToolName
    arguments: dict[str, JsonValue]
    success: bool
    code: str
    message: str
    source: str
    trace_id: str
    duration_ms: int = Field(ge=0)
    data: JsonValue | None = None


class AnalysisExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: AnalysisPlan
    steps: list[AnalysisStepResult]
    successful_steps: int
    failed_steps: int
    partial_success: bool


class AnalysisTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    rows: list[dict[str, JsonValue]]
    total: int | None = None


class AnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    plan: AnalysisPlan
    effective_query: AnalyticsQueryInput | None = None
    datasets: dict[str, JsonValue] = Field(default_factory=dict)
    summary: dict[str, JsonValue] = Field(default_factory=dict)
    groups: list[dict[str, JsonValue]] = Field(default_factory=list)
    candidates: list[dict[str, JsonValue]] = Field(default_factory=list)
    table: AnalysisTable | None = None
    step_results: list[AnalysisStepResult]
    warnings: list[str] = Field(default_factory=list)
    partial_success: bool = False
