"""Unified Langfuse caller facade for CoreAgent-style LLM calls."""

from __future__ import annotations

from typing import Any

from soothe_sdk.observability.langfuse._client import resolve_langfuse_config_str
from soothe_sdk.observability.langfuse._merge import merge_langfuse_runnable_config
from soothe_sdk.observability.langfuse._trace_io import patch_langfuse_trace_goal_io
from soothe_sdk.observability.langfuse._types import SootheConfigLike


def create_llm_call_metadata(
    purpose: str,
    component: str,
    phase: str = "unknown",
    **extra: Any,
) -> dict[str, Any]:
    """Create standardized metadata for LLM calls."""
    metadata = {
        "soothe_call_purpose": purpose,
        "soothe_call_component": component,
        "soothe_call_phase": phase,
    }
    metadata.update(extra)
    return metadata


class SootheLangfuse:
    """Langfuse RunnableConfig helpers for CoreAgent LLM calls."""

    def __init__(self, soothe_config: SootheConfigLike | None) -> None:
        self._config = soothe_config

    @property
    def config(self) -> SootheConfigLike | None:
        return self._config

    @property
    def enabled(self) -> bool:
        if self._config is None:
            return False
        return self._config.observability.langfuse.enabled

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
        goal_trace: Any | None = None,
    ) -> dict[str, Any]:
        """RunnableConfig for a standalone or nested LLM ``ainvoke`` / ``astream``."""
        if goal_trace is not None and hasattr(goal_trace, "intake_invoke_config"):
            return goal_trace.intake_invoke_config(
                purpose=purpose,
                component=component,
                phase=phase,
                extra_metadata=extra_metadata,
            )

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
        goal_trace: Any | None = None,
    ) -> dict[str, Any]:
        """Merge Langfuse callbacks into an existing RunnableConfig."""
        if self._config is None:
            return base
        pinned = getattr(goal_trace, "trace_id", None) if goal_trace is not None else None
        return merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=session_id,
            run_name=run_name,
            loop_id=loop_id,
            inherit_callbacks_from=inherit_callbacks_from,
            fresh_handler=fresh_handler,
            pinned_trace_id=pinned,
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
        pub = resolve_langfuse_config_str(self._config.observability.langfuse.public_key)
        patch_langfuse_trace_goal_io(
            config,
            goal_text=goal_text,
            output_text=output_text,
            trace_display_name=trace_display_name,
            session_id=session_id,
            public_key=pub,
        )
