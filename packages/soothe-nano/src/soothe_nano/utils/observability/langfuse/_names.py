"""Langfuse trace/run display names for goal-loop stages."""


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Root run label for ``strange-loop-graph`` / LangGraph ``run_name``."""
    tn = (trace_name or "").strip()
    return f"{tn}:strange-loop-graph" if tn else "strange-loop-graph"


def intent_classify_langfuse_run_display_name(trace_name: str | None) -> str:
    """Child run label for the pre-graph intake LLM under the goal loop trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:intent-classify" if tn else "intent-classify"


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Child run label for Execute-phase CoreAgent streams under the goal loop trace."""
    tn = (trace_name or "").strip()
    return f"{tn}:execute-step" if tn else "execute-step"
