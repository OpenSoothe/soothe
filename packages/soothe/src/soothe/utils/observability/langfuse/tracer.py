"""Unified Langfuse caller facade for the Soothe codebase."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe.utils.observability.langfuse._goal_loop import GoalLoopTrace
from soothe.utils.observability.langfuse._merge import merge_langfuse_runnable_config
from soothe.utils.observability.langfuse._trace_io import patch_langfuse_trace_goal_io

if TYPE_CHECKING:
    from soothe.config import SootheConfig


class SootheLangfuse:
    """Single entry point for Langfuse RunnableConfig and goal-loop trace sessions."""

    def __init__(self, soothe_config: SootheConfig | None) -> None:
        self._config = soothe_config

    @property
    def config(self) -> SootheConfig | None:
        return self._config

    @property
    def enabled(self) -> bool:
        if self._config is None:
            return False
        return self._config.observability.langfuse.enabled

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

    def traced_llm(
        self,
        *,
        purpose: str,
        component: str,
        phase: str = "pre-stream",
        session_id: str | None = None,
        run_name: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        loop_id: str | None = None,
        independent_trace: bool = False,
        goal_trace: GoalLoopTrace | None = None,
    ) -> dict[str, Any]:
        """RunnableConfig for a standalone or nested LLM ``ainvoke`` / ``astream``."""
        if goal_trace is not None:
            return goal_trace.intake_invoke_config(
                purpose=purpose,
                component=component,
                phase=phase,
                extra_metadata=extra_metadata,
            )

        from soothe.middleware._utils import create_llm_call_metadata

        metadata = create_llm_call_metadata(purpose=purpose, component=component, phase=phase)
        if extra_metadata:
            metadata.update(extra_metadata)

        base: dict[str, Any] = {"metadata": metadata}
        if self._config is None:
            return base
        return merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=session_id,
            run_name=run_name,
            loop_id=loop_id,
            fresh_handler=independent_trace,
        )

    def merge(
        self,
        base: dict[str, Any],
        *,
        session_id: str | None = None,
        run_name: str | None = None,
        loop_id: str | None = None,
        inherit_callbacks_from: dict[str, Any] | None = None,
        fresh_handler: bool = False,
        goal_trace: GoalLoopTrace | None = None,
    ) -> dict[str, Any]:
        """Merge Langfuse callbacks into an existing RunnableConfig."""
        if self._config is None:
            return base
        return merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=session_id,
            run_name=run_name,
            loop_id=loop_id,
            inherit_callbacks_from=inherit_callbacks_from,
            fresh_handler=fresh_handler,
            pinned_trace_id=goal_trace.trace_id if goal_trace else None,
        )

    def patch_goal_io(
        self,
        config: dict[str, Any],
        *,
        goal_text: str,
        output_text: str,
        trace_display_name: str,
        session_id: str | None = None,
    ) -> None:
        """Set trace-level input/output after graph completion."""
        if self._config is None:
            return
        from soothe.utils.observability.langfuse._client import resolve_langfuse_config_str

        pub = resolve_langfuse_config_str(self._config.observability.langfuse.public_key)
        patch_langfuse_trace_goal_io(
            config,
            goal_text=goal_text,
            output_text=output_text,
            trace_display_name=trace_display_name,
            session_id=session_id,
            public_key=pub,
        )
