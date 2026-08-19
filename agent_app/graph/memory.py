from agent_app.graph.schemas import GraphRunRequest, GraphRunResult, PendingAction, RouteType
from agent_app.models.role_schemas import FormClassificationData
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
    def pending_action(request: GraphRunRequest) -> PendingAction | None:
        if request.restored_state is None:
            return None
        value = request.restored_state.collected_data.get("pending_action")
        if not isinstance(value, dict):
            return None
        try:
            return PendingAction.model_validate(value)
        except ValueError:
            return None

    @staticmethod
    def form_draft(request: GraphRunRequest) -> dict:
        if request.restored_state is None:
            return {}
        value = request.restored_state.collected_data.get("form_draft")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def form_classification(request: GraphRunRequest) -> FormClassificationData | None:
        if request.restored_state is None:
            return None
        value = request.restored_state.collected_data.get("form_classification")
        if not isinstance(value, dict):
            return None
        try:
            return FormClassificationData.model_validate(value)
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
        if result.knowledge is not None:
            collected_data["last_knowledge"] = {
                "query": result.knowledge.original_query,
                "citation_ids": [item.citation_id for item in result.knowledge.citations],
                "retrieval_trace_id": result.knowledge.trace.trace_id,
            }
        if result.review is not None:
            collected_data["last_review"] = result.review.model_dump(mode="json")
        last_recommendations = list(previous.last_recommendations if previous else [])
        if result.recommendation is not None:
            last_recommendations = [result.recommendation.compact_state()]
        if result.pending_action is not None:
            collected_data["pending_action"] = result.pending_action.model_dump(mode="json")
        else:
            collected_data.pop("pending_action", None)
        if result.form_draft:
            collected_data["form_draft"] = result.form_draft
            collected_data["form_missing_fields"] = result.form_missing_fields
            if result.form_classification is not None:
                collected_data["form_classification"] = result.form_classification.model_dump(
                    mode="json"
                )
            else:
                collected_data.pop("form_classification", None)
        elif result.route is RouteType.FORM_PREFILL:
            collected_data.pop("form_draft", None)
            collected_data.pop("form_missing_fields", None)
            collected_data.pop("form_classification", None)
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
            missing_fields=(
                result.form_missing_fields
                if result.route is RouteType.FORM_PREFILL
                else ["requirement_reference"]
                if needs_request_id
                else []
            ),
            pending_field=(
                result.form_missing_fields[0]
                if result.route is RouteType.FORM_PREFILL and result.form_missing_fields
                else "requirement_reference"
                if needs_request_id
                else None
            ),
            awaiting_confirmation=result.pending_action is not None,
            recent_messages=recent_messages[-10:],
            last_recommendations=last_recommendations,
        )
