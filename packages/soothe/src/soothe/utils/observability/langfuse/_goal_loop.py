"""Goal-loop Langfuse trace session (intent-classify + strange-loop-graph)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.utils.observability.langfuse._client import resolve_str, resolved_langfuse_tags
from soothe.utils.observability.langfuse._handlers import allocate_langfuse_trace_id
from soothe.utils.observability.langfuse._merge import merge_langfuse_runnable_config
from soothe.utils.observability.langfuse._names import (
    intent_classify_langfuse_run_display_name,
    loop_graph_langfuse_run_display_name,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig


@dataclass(frozen=True)
class GoalLoopTrace:
    """Shared Langfuse trace for one agentic goal turn (IG-540).

    Stages use a fresh handler pinned to ``trace_id`` so LangChain invocations do not
    open separate root traces. Pass through runner → classifier → graph invoke.
    """

    soothe_config: SootheConfig
    trace_id: str | None
    session_id: str | None
    loop_id: str | None
    trace_display_name: str

    @classmethod
    def begin(
        cls,
        soothe_config: SootheConfig,
        *,
        session_id: str | None,
        loop_id: str | None,
    ) -> GoalLoopTrace:
        """Allocate trace id and metadata for a new goal-loop turn."""
        trace_name = (soothe_config.observability.langfuse.trace_name or "").strip()
        display = loop_graph_langfuse_run_display_name(trace_name or None)
        trace_id = (
            allocate_langfuse_trace_id(soothe_config)
            if soothe_config.observability.langfuse.enabled
            else None
        )
        return cls(
            soothe_config=soothe_config,
            trace_id=trace_id,
            session_id=session_id,
            loop_id=loop_id,
            trace_display_name=display,
        )

    @property
    def enabled(self) -> bool:
        return self.soothe_config.observability.langfuse.enabled

    def _configurable(self) -> dict[str, Any]:
        return {"thread_id": self.loop_id or self.session_id or ""}

    def base_metadata(self) -> dict[str, Any]:
        """Metadata shared by all stages on this trace."""
        meta: dict[str, Any] = {}
        if self.session_id:
            meta["langfuse_session_id"] = self.session_id
            meta["thread_id"] = self.session_id
        if self.loop_id:
            meta["loop_id"] = self.loop_id
        if self.trace_id:
            meta["langfuse_trace_id"] = self.trace_id
        tags_cfg = resolved_langfuse_tags(self.soothe_config)
        tags = list(tags_cfg) if tags_cfg else []
        for label in ("goal_execution_loop", "strange-loop-graph"):
            if label not in tags:
                tags.append(label)
        if tags:
            meta["langfuse_tags"] = tags
        uid = resolve_str(self.soothe_config.observability.langfuse.user_id)
        if uid:
            meta["langfuse_user_id"] = uid
        meta.setdefault("soothe_component", "strange_loop_graph")
        meta.setdefault("soothe_component_version", "strange-loop-v2")
        meta["langfuse_trace_name"] = self.trace_display_name
        return meta

    def intake_invoke_config(
        self,
        *,
        purpose: str,
        component: str,
        phase: str = "pre-stream",
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """RunnableConfig for off-graph intent-classify under this trace."""
        from soothe.middleware._utils import create_llm_call_metadata

        metadata = create_llm_call_metadata(purpose=purpose, component=component, phase=phase)
        if extra_metadata:
            metadata.update(extra_metadata)

        trace_name = (self.soothe_config.observability.langfuse.trace_name or "").strip()
        run_name = intent_classify_langfuse_run_display_name(trace_name or None)

        base: dict[str, Any] = {
            "configurable": dict(self._configurable()),
            "metadata": {**self.base_metadata(), **metadata},
        }
        return merge_langfuse_runnable_config(
            base,
            self.soothe_config,
            session_id=self.session_id,
            run_name=run_name,
            loop_id=self.loop_id,
            pinned_trace_id=self.trace_id,
        )

    def graph_invoke_config(
        self,
        *,
        configurable: dict[str, Any],
    ) -> dict[str, Any]:
        """RunnableConfig for ``CompiledGraph.ainvoke`` under this trace."""
        base: dict[str, Any] = {
            "configurable": dict(configurable),
            "metadata": dict(self.base_metadata()),
            "run_name": self.trace_display_name,
        }
        merged = merge_langfuse_runnable_config(
            base,
            self.soothe_config,
            session_id=self.session_id,
            run_name=self.trace_display_name,
            loop_id=self.loop_id,
            pinned_trace_id=self.trace_id,
        )
        out = dict(merged)
        meta = dict(out.get("metadata") or {})
        meta.setdefault("loop_id", self.loop_id or "")
        meta.setdefault("soothe_component", "strange_loop_graph")
        meta.setdefault("soothe_component_version", "strange-loop-v2")
        tags = list(meta.get("langfuse_tags") or [])
        for label in ("goal_execution_loop", "strange-loop-graph"):
            if label not in tags:
                tags.append(label)
        meta["langfuse_tags"] = tags
        out["metadata"] = meta
        return out
