"""Host-specific Langfuse display-name helpers for StrangeLoop runtime (IG-663).

Run-name suffixes align with stem stations where they name a graph station
or the primary LLM under that station. Kebab-case matches existing Langfuse
tags (``strange-loop-graph``, ``execute-step``).
"""

_HOST_LOOP_GRAPH_RUN_NAME = "strange-loop-graph"
_HOST_INTAKE_RUN_NAME = "intake"
_HOST_EXECUTE_STEP_RUN_NAME = "execute-step"


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host root graph run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_LOOP_GRAPH_RUN_NAME}" if tn else _HOST_LOOP_GRAPH_RUN_NAME


def intake_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host preprocess ``intake`` child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_INTAKE_RUN_NAME}" if tn else _HOST_INTAKE_RUN_NAME


# Historical alias (IG-540 / pre-IG-663).
intent_classify_langfuse_run_display_name = intake_langfuse_run_display_name


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host CoreAgent execute-step child run display name for a trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:{_HOST_EXECUTE_STEP_RUN_NAME}" if tn else _HOST_EXECUTE_STEP_RUN_NAME


__all__ = [
    "execute_step_langfuse_run_display_name",
    "intake_langfuse_run_display_name",
    "intent_classify_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
]
