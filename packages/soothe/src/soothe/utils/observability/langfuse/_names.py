"""Host-specific Langfuse display-name helpers for StrangeLoop runtime.

Run-name suffixes align with stem stations. Kebab-case matches existing
Langfuse tags (``strange-loop-graph``, ``execute-step``).
"""

_HOST_LOOP_GRAPH_RUN_NAME = "strange-loop-graph"
_HOST_INTAKE_RUN_NAME = "intake"
_HOST_INTAKE_PHASE_RUN_NAMES = {
    "intake_pass1": "intake-pass1",
    "strange_loop_graph": "intake-classify",
}
_HOST_EXECUTE_STEP_RUN_NAME = "execute-step"
_HOST_FINALIZE_RUN_NAME = "finalize"


def _with_trace_prefix(trace_name: str | None, suffix: str) -> str:
    tn = (trace_name or "").strip()
    return f"{tn}:{suffix}" if tn else suffix


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host root graph run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_LOOP_GRAPH_RUN_NAME)


def intake_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host preprocess ``intake`` child run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_INTAKE_RUN_NAME)


def intake_phase_langfuse_run_display_name(trace_name: str | None, phase: str) -> str | None:
    """Return the child run name under ``intake`` for a phase, or None when unmapped."""
    suffix = _HOST_INTAKE_PHASE_RUN_NAMES.get(phase)
    if suffix is None:
        return None
    return _with_trace_prefix(trace_name, suffix)


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host CoreAgent execute-step child run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_EXECUTE_STEP_RUN_NAME)


def finalize_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return finalize / goal-completion synthesis run display name."""
    return _with_trace_prefix(trace_name, _HOST_FINALIZE_RUN_NAME)


__all__ = [
    "execute_step_langfuse_run_display_name",
    "finalize_langfuse_run_display_name",
    "intake_langfuse_run_display_name",
    "intake_phase_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
]
