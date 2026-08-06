from agent_app.graph.schemas import GraphRunRequest, GraphRunResult, RouteType
from agent_app.schemas.analytics import AnalyticsQueryInput
from agent_app.schemas.backend import ConversationStatePayload


class GraphMemoryMapper:
    @staticmethod
    def purchase_request_id(request: GraphRunRequest) -> int | None:
        if request.restored_state is None:
            return None
        return request.restored_state.purchase_request_id

    @staticmethod
    def analysis_query(request: GraphRunRequest) -> AnalyticsQueryInput | None:
        if request.restored_state is None:
            return None
        value = request.restored_state.collected_data.get("analysis_query_context")
        if not isinstance(value, dict):
            return None
        try:
            return AnalyticsQueryInput.model_validate(value)
        except ValueError:
            return None

    @staticmethod
    def to_backend_state(
        request: GraphRunRequest,
        result: GraphRunResult,
    ) -> ConversationStatePayload:
        previous = request.restored_state
        collected_data = dict(previous.collected_data if previous else {})
        collected_data.update(
            {
                "last_task_id": str(result.task_id),
                "last_trace_id": result.trace_id,
                "last_route": result.route.value,
                "requirement_id": result.purchase_request_id,
                "last_tool_results": [item.model_dump(mode="json") for item in result.tool_results],
                "last_trace_events": [item.model_dump(mode="json") for item in result.trace_events],
                "last_errors": [item.model_dump(mode="json") for item in result.errors],
            }
        )
        if result.analysis is not None:
            collected_data["last_analysis"] = result.analysis.model_dump(mode="json")
            if result.analysis.effective_query is not None:
                collected_data["analysis_query_context"] = (
                    result.analysis.effective_query.model_dump(mode="json")
                )
        if result.risk_investigation is not None:
            collected_data["last_risk_investigation"] = result.risk_investigation.model_dump(
                mode="json"
            )
        recent_messages = list(previous.recent_messages if previous else [])
        recent_messages.extend(
            [
                {"sender_type": "USER", "content": request.message},
                {"sender_type": "AGENT", "content": result.reply},
            ]
        )
        needs_request_id = (
            result.route
            in {
                RouteType.REALTIME_BUSINESS,
                RouteType.HYBRID,
            }
            and result.purchase_request_id is None
        )
        return ConversationStatePayload(
            purchase_request_id=result.purchase_request_id,
            current_action="CHAT",
            collected_data=collected_data,
            missing_fields=["purchase_request_id"] if needs_request_id else [],
            pending_field="purchase_request_id" if needs_request_id else None,
            awaiting_confirmation=False,
            recent_messages=recent_messages[-10:],
            last_recommendations=list(previous.last_recommendations if previous else []),
        )
