"""Langfuse integration for soothe (CoreAgent helpers + goal-loop tracing)."""

from __future__ import annotations

from soothe_sdk.observability.langfuse import (
    SootheLangfuse as _SdkSootheLangfuse,
)
from soothe_sdk.observability.langfuse import (
    merge_langfuse_runnable_config,
    resolve_langfuse_config_str,
)
from soothe_sdk.observability.langfuse._trace_io import (
    patch_langfuse_trace_goal_io,
)

from soothe.utils.observability.langfuse._client import flush_langfuse_events
from soothe.utils.observability.langfuse._goal_loop import GoalLoopTrace
from soothe.utils.observability.langfuse._intake_span import (
    IntakeLangfuseSpan,
    open_intake_langfuse_span,
)
from soothe.utils.observability.langfuse._names import (
    execute_step_langfuse_run_display_name,
    finalize_langfuse_run_display_name,
    intake_langfuse_run_display_name,
    intake_phase_langfuse_run_display_name,
    loop_graph_langfuse_run_display_name,
)


class SootheLangfuse(_SdkSootheLangfuse):
    """Soothe Langfuse facade with StrangeLoop goal-loop sessions."""

    def begin_goal_loop(
        self,
        *,
        session_id: str | None,
        loop_id: str | None,
    ) -> GoalLoopTrace | None:
        """Start a shared trace for intake + strange-loop-graph."""
        if not self.enabled or self._config is None:
            return None
        return GoalLoopTrace.begin(
            self._config,
            session_id=session_id,
            loop_id=loop_id,
        )

    def flush(self) -> None:
        """Export buffered observations for turns that end before the graph runs."""
        if not self.enabled or self._config is None:
            return
        flush_langfuse_events(self._config)


__all__ = [
    "GoalLoopTrace",
    "IntakeLangfuseSpan",
    "SootheLangfuse",
    "execute_step_langfuse_run_display_name",
    "finalize_langfuse_run_display_name",
    "flush_langfuse_events",
    "intake_langfuse_run_display_name",
    "intake_phase_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
    "merge_langfuse_runnable_config",
    "open_intake_langfuse_span",
    "patch_langfuse_trace_goal_io",
    "resolve_langfuse_config_str",
]
