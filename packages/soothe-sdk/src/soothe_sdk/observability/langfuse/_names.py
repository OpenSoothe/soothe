"""Shared Langfuse trace/run display-name helpers for Nano runtime."""

_ROOT_GRAPH_RUN_NAME = "nanoagent-graph"
_INTAKE_CLASSIFY_RUN_NAME = "intake-classify"
_EXECUTE_STEP_RUN_NAME = "execute-step"


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return the root graph run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_ROOT_GRAPH_RUN_NAME}" if tn else _ROOT_GRAPH_RUN_NAME


def intent_classify_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return the intake classifier child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_INTAKE_CLASSIFY_RUN_NAME}" if tn else _INTAKE_CLASSIFY_RUN_NAME


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return the execute-phase child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_EXECUTE_STEP_RUN_NAME}" if tn else _EXECUTE_STEP_RUN_NAME
