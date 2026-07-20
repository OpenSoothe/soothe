"""Host-specific Langfuse display-name helpers for StrangeLoop runtime."""

_HOST_LOOP_GRAPH_RUN_NAME = "strange-loop-graph"
_HOST_INTENT_CLASSIFY_RUN_NAME = "intent-classify"
_HOST_EXECUTE_STEP_RUN_NAME = "execute-step"


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host root graph run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_LOOP_GRAPH_RUN_NAME}" if tn else _HOST_LOOP_GRAPH_RUN_NAME


def intent_classify_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host intent-classify child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_INTENT_CLASSIFY_RUN_NAME}" if tn else _HOST_INTENT_CLASSIFY_RUN_NAME


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host execute-step child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_EXECUTE_STEP_RUN_NAME}" if tn else _HOST_EXECUTE_STEP_RUN_NAME


__all__ = [
    "execute_step_langfuse_run_display_name",
    "intent_classify_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
]
