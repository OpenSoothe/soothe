"""Langfuse integration for soothe (CoreAgent helpers + goal-loop tracing)."""

from __future__ import annotations

from typing import Any

from soothe_nano.utils.observability import langfuse as nano_langfuse
from soothe_nano.utils.observability.langfuse import (
    merge_langfuse_runnable_config,
    resolve_langfuse_config_str,
)

from soothe.utils.observability.langfuse._goal_loop import GoalLoopTrace
from soothe.utils.observability.langfuse._names import (
    intent_classify_langfuse_run_display_name,
    loop_graph_langfuse_run_display_name,
)
from soothe.utils.observability.langfuse._trace_io import patch_langfuse_trace_goal_io


class SootheLangfuse(nano_langfuse.SootheLangfuse):
    """Soothe Langfuse facade with StrangeLoop goal-loop sessions."""

    def begin_goal_loop(
        self,
        *,
        session_id: str | None,
        loop_id: str | None,
    ) -> GoalLoopTrace | None:
        """Start a shared trace for intent-classify + strange-loop-graph."""
        if not self.enabled or self._config is None:
            return None
        return GoalLoopTrace.begin(
            self._config,
            session_id=session_id,
            loop_id=loop_id,
        )


__all__ = [
    "GoalLoopTrace",
    "SootheLangfuse",
    "intent_classify_langfuse_run_display_name",
    "loop_graph_langfuse_run_display_name",
    "merge_langfuse_runnable_config",
    "patch_langfuse_trace_goal_io",
    "resolve_langfuse_config_str",
]


def __getattr__(name: str) -> Any:
    from importlib import import_module

    return getattr(import_module("soothe_nano.utils.observability.langfuse"), name)
