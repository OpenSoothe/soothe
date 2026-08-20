"""Shared RunnableConfig builders for intake classification LLM calls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from soothe.config import SootheConfig

IntakePhase = Literal["intake_classify"]

_DEFAULT_RUN_NAMES: dict[IntakePhase, str] = {
    "intake_classify": "intake-classify",
}


def build_intake_invoke_config(
    *,
    phase: IntakePhase,
    purpose: str,
    component: str,
    soothe_config: SootheConfig | None = None,
    observability_metadata: dict[str, str] | None = None,
    goal_trace: Any | None = None,
    inherit_callbacks_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build RunnableConfig with Langfuse tracing for an intake classification call."""
    from soothe_nano.llm import build_traced_invoke_config

    if goal_trace is not None:
        return goal_trace.intake_invoke_config(
            purpose=purpose,
            component=f"classifier.{component}",
            phase=phase,
            extra_metadata=observability_metadata,
            inherit_callbacks_from=inherit_callbacks_from,
        )

    from soothe.utils.observability.langfuse import intake_phase_langfuse_run_display_name

    trace_name = (
        (soothe_config.observability.langfuse.trace_name or "").strip()
        if soothe_config is not None
        else ""
    )
    return build_traced_invoke_config(
        soothe_config=soothe_config,
        purpose=purpose,
        component=f"classifier.{component}",
        phase=phase,
        session_id=None,
        loop_id=None,
        run_name=intake_phase_langfuse_run_display_name(trace_name or None, phase)
        or _DEFAULT_RUN_NAMES[phase],
        extra_metadata=observability_metadata,
        goal_trace=None,
        independent_trace=False,
    )


__all__ = ["IntakePhase", "build_intake_invoke_config"]
