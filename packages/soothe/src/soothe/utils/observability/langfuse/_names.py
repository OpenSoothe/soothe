"""Host-specific Langfuse display-name helpers for StrangeLoop runtime."""

_HOST_LOOP_GRAPH_RUN_NAME = "strange-loop-graph"
_HOST_INTAKE_PHASE_RUN_NAMES = {
    "intake_classify": "intake-classify",
}
_HOST_EXECUTE_STEP_RUN_NAME = "execute-step"
_HOST_STEP_COMPLETION_REPORT_RUN_NAME = "step-completion-report"
_HOST_STEP_DELIVERABLE_RUN_NAME = "step-deliverable"
_HOST_FINALIZE_RUN_NAME = "finalize"


def _with_trace_prefix(trace_name: str | None, suffix: str) -> str:
    tn = (trace_name or "").strip()
    return f"{tn}:{suffix}" if tn else suffix


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host root graph run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_LOOP_GRAPH_RUN_NAME)


def intake_phase_langfuse_run_display_name(trace_name: str | None, phase: str) -> str | None:
    """Return the child run name under `intake` for a phase, or None when unmapped."""
    suffix = _HOST_INTAKE_PHASE_RUN_NAMES.get(phase)
    if suffix is None:
        return None
    return _with_trace_prefix(trace_name, suffix)


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host CoreAgent execute-step child run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_EXECUTE_STEP_RUN_NAME)


def step_completion_report_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host step-completion TUI cognition summary run display name."""
    return _with_trace_prefix(trace_name, _HOST_STEP_COMPLETION_REPORT_RUN_NAME)


def step_deliverable_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host step-deliverable LLM verdict run display name."""
    return _with_trace_prefix(trace_name, _HOST_STEP_DELIVERABLE_RUN_NAME)


def finalize_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return finalize / goal-completion synthesis run display name."""
    return _with_trace_prefix(trace_name, _HOST_FINALIZE_RUN_NAME)


__all__ = [
    "execute_step_langfuse_run_display_name",
    "finalize_langfuse_run_display_name",
    "intake_phase_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
    "step_completion_report_langfuse_run_display_name",
    "step_deliverable_langfuse_run_display_name",
]
