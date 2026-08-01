"""Host-specific Langfuse display-name helpers for StrangeLoop runtime (IG-663 / IG-672).

Run-name suffixes align with stem stations where they name a graph station
or the primary LLM under that station. Kebab-case matches existing Langfuse
tags (``strange-loop-graph``, ``execute-step``).

Evaluate subgraph (IG-672): parent ``evaluate`` with children
``evaluate-gap`` / ``evaluate-gap-leg-{i}`` / ``evaluate-assess``.
"""

_HOST_LOOP_GRAPH_RUN_NAME = "strange-loop-graph"
_HOST_INTAKE_RUN_NAME = "intake"
_HOST_EXECUTE_STEP_RUN_NAME = "execute-step"
_HOST_EVALUATE_RUN_NAME = "evaluate"
_HOST_EVALUATE_GAP_RUN_NAME = "evaluate-gap"
_HOST_EVALUATE_ASSESS_RUN_NAME = "evaluate-assess"
_HOST_EVALUATE_ASSESS_CONTINUATION_RUN_NAME = "evaluate-assess-continuation"


def _with_trace_prefix(trace_name: str | None, suffix: str) -> str:
    tn = (trace_name or "").strip()
    return f"{tn}:{suffix}" if tn else suffix


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host root graph run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_LOOP_GRAPH_RUN_NAME)


def intake_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host preprocess ``intake`` child run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_INTAKE_RUN_NAME)


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return host CoreAgent execute-step child run display name for a trace."""
    return _with_trace_prefix(trace_name, _HOST_EXECUTE_STEP_RUN_NAME)


def evaluate_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return parent evaluate-station span name (IG-672)."""
    return _with_trace_prefix(trace_name, _HOST_EVALUATE_RUN_NAME)


def evaluate_gap_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return sequential inventory (gap) child run name under evaluate."""
    return _with_trace_prefix(trace_name, _HOST_EVALUATE_GAP_RUN_NAME)


def evaluate_gap_leg_langfuse_run_display_name(
    trace_name: str | None,
    *,
    leg_index: int,
) -> str:
    """Return parallel inventory leg child run name under evaluate."""
    return _with_trace_prefix(trace_name, f"evaluate-gap-leg-{leg_index}")


def evaluate_assess_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return assess child run name under evaluate."""
    return _with_trace_prefix(trace_name, _HOST_EVALUATE_ASSESS_RUN_NAME)


def evaluate_assess_continuation_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return continuation-assess child run name under evaluate."""
    return _with_trace_prefix(trace_name, _HOST_EVALUATE_ASSESS_CONTINUATION_RUN_NAME)


__all__ = [
    "evaluate_assess_continuation_langfuse_run_display_name",
    "evaluate_assess_langfuse_run_display_name",
    "evaluate_gap_langfuse_run_display_name",
    "evaluate_gap_leg_langfuse_run_display_name",
    "evaluate_langfuse_run_display_name",
    "execute_step_langfuse_run_display_name",
    "intake_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
]
