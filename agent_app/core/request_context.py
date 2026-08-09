from contextvars import ContextVar

trace_id_context: ContextVar[str | None] = ContextVar("agent_trace_id", default=None)
