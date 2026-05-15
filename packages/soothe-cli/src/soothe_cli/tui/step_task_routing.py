"""Per-turn routing for AgentLoop steps, root tools, and subagent task namespaces.

Owns associations between execute ``step_id``, root ``tool_call_id``, LangGraph
subgraph ``namespace``, and ``task`` delegations. Designed for parallel execute waves
where a single "active step" hint is unreliable.

The SDK helpers in ``soothe_sdk.ux.task_namespace`` remain the pure binding core;
this module adds TUI-oriented buffers and lifecycle for multiple concurrent steps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from soothe_sdk.ux.task_namespace import (
    TaskScope,
    maybe_bind_namespace,
    register_task_spawn_for_step,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    task_scope_step_id,
)

StepWidget: TypeAlias = Any
"""``CognitionStepMessage`` or compatible step card (duck-typed)."""

ParentWidget: TypeAlias = Any
"""Step card or ``ToolCallMessage`` parent for tool rows / subagent activity."""


@dataclass(slots=True)
class PendingMainTool:
    """Root-graph tool call waiting for a step card or step binding."""

    tool_call_id: str
    name: str
    args: dict[str, Any]
    raw_args: str = ""


@dataclass(slots=True)
class PendingSubgraphTool:
    """Subgraph tool call waiting for namespace → task scope resolution."""

    ns_key: tuple[str, ...]
    lookup_id: str
    display_key: str
    tool_name: str
    args: dict[str, Any]
    raw_args: str = ""


@dataclass
class StepTaskRouter:
    """High-performance per-turn router for steps, tools, and task namespaces.

    Attributes:
        active_step_ids: Execute steps currently in the running phase.
        tool_call_to_step_id: Root ``tool_call_id`` → ``step_id`` map (legacy fallback).
    """

    active_step_ids: set[str] = field(default_factory=set)
    tool_call_to_step_id: dict[str, str] = field(default_factory=dict)

    _task_spawn_queue: deque[TaskScope] = field(default_factory=deque, repr=False)
    _namespace_bindings: dict[tuple[str, ...], TaskScope] = field(default_factory=dict, repr=False)
    _spawns_by_step_id: dict[str, TaskScope] = field(default_factory=dict, repr=False)
    _pending_unscoped_namespaces: deque[tuple[str, ...]] = field(default_factory=deque, repr=False)
    _spawn_recorded: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _pending_main_tools: list[PendingMainTool] = field(default_factory=list, repr=False)
    _pending_subgraph_tools: list[PendingSubgraphTool] = field(default_factory=list, repr=False)

    def reset_turn(self) -> None:
        """Clear all per-turn routing state."""
        self.active_step_ids.clear()
        self.tool_call_to_step_id.clear()
        self._task_spawn_queue.clear()
        self._namespace_bindings.clear()
        self._spawns_by_step_id.clear()
        self._pending_unscoped_namespaces.clear()
        self._spawn_recorded.clear()
        self._pending_main_tools.clear()
        self._pending_subgraph_tools.clear()

    # --- Step lifecycle ---

    def on_step_started(self, step_id: str) -> None:
        """Track a step entering the running phase."""
        sid = step_id.strip()
        if sid:
            self.active_step_ids.add(sid)

    def on_step_completed(self, step_id: str) -> None:
        """Drop step from the active set and spawn registry."""
        sid = step_id.strip()
        if sid:
            self.active_step_ids.discard(sid)
            self._spawns_by_step_id.pop(sid, None)

    def bind_tool_to_step(self, tool_call_id: str, step_id: str) -> None:
        """Record tool_call_id → step_id mapping (legacy fallback for non-unified IDs)."""
        tcid = str(tool_call_id).strip()
        sid = str(step_id).strip()
        if tcid and sid:
            self.tool_call_to_step_id[tcid] = sid

    def step_id_for_tool(self, tool_call_id: str) -> str:
        """Return bound execute step id for a root tool call, if any."""
        return self.tool_call_to_step_id.get(str(tool_call_id).strip(), "")

    # --- Namespace / task spawn ---

    def on_subgraph_namespace(self, namespace: tuple[str, ...]) -> None:
        """Bind or defer a delegated subgraph namespace."""
        if not namespace:
            return
        maybe_bind_namespace(
            self._namespace_bindings,
            self._task_spawn_queue,
            namespace,
            pending_unscoped_namespaces=self._pending_unscoped_namespaces,
        )

    def register_task_spawn(
        self,
        tool_call_id: str,
        subagent_type: str,
        *,
        step_id: str = "",
    ) -> bool:
        """Register a main-graph ``task`` spawn and bind deferred namespaces.

        Returns:
            True when this ``(step_id, tool_call_id)`` pair is newly recorded.
        """
        tcid = str(tool_call_id).strip()
        if not tcid:
            return False
        sid = (step_id or self.step_id_for_tool(tcid)).strip()
        spawn_key = (sid, tcid)
        if spawn_key in self._spawn_recorded:
            return False
        scope: TaskScope = (tcid, (subagent_type or "?").strip() or "?", sid)
        register_task_spawn_for_step(
            self._namespace_bindings,
            self._task_spawn_queue,
            self._spawns_by_step_id,
            scope,
            pending_unscoped_namespaces=self._pending_unscoped_namespaces,
        )
        self._spawn_recorded.add(spawn_key)
        return True

    def resolve_task_scope(self, namespace: tuple[str, ...]) -> TaskScope | None:
        """Task scope for a stream namespace, if bound."""
        return resolve_task_scope_for_namespace(self._namespace_bindings, namespace)

    def resolve_parent(
        self,
        scope: TaskScope | None,
        *,
        step_cards: dict[str, StepWidget],
        tool_display_by_call_id: dict[str, ParentWidget],
    ) -> ParentWidget | None:
        """Parent widget for subagent rows / activity lines."""
        return resolve_task_parent_lookup(
            scope,
            step_cards=step_cards,
            tool_display_by_call_id=tool_display_by_call_id,
        )

    def task_scope_step_id(self, scope: TaskScope | None) -> str:
        """Step id from a resolved task scope."""
        return task_scope_step_id(scope)

    # --- Pending main-graph tools ---

    def buffer_main_tool(
        self,
        tool_call_id: str,
        name: str,
        args: dict[str, Any],
        *,
        raw_args: str = "",
    ) -> None:
        """Queue a root tool until its step card or binding is available."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return
        self._pending_main_tools.append(
            PendingMainTool(
                tool_call_id=tcid,
                name=name or "tool",
                args=dict(args or {}),
                raw_args=raw_args,
            )
        )

    def route_pending_main_tools(
        self,
        step_cards: dict[str, StepWidget],
        tool_to_step: dict[str, ParentWidget],
        tool_display_by_call_id: dict[str, ParentWidget],
    ) -> int:
        """Attach buffered root tools to step cards when binding or cards exist.

        Returns:
            Number of tools routed out of the pending buffer.
        """
        if not self._pending_main_tools:
            return 0
        still: list[PendingMainTool] = []
        routed = 0
        for item in self._pending_main_tools:
            bound = self.step_id_for_tool(item.tool_call_id)
            if not bound:
                still.append(item)
                continue
            step_w = step_cards.get(bound)
            if step_w is None:
                still.append(item)
                continue
            ingest = getattr(step_w, "add_tool_call", None)
            if not callable(ingest):
                still.append(item)
                continue
            if not getattr(step_w, "has_tool_call_row", lambda _x: False)(item.tool_call_id):
                ingest(
                    item.tool_call_id,
                    item.name,
                    item.args,
                    raw_args=item.raw_args,
                )
            tool_to_step[item.tool_call_id] = step_w
            existing = tool_display_by_call_id.get(item.tool_call_id)
            if existing is None:
                tool_display_by_call_id[item.tool_call_id] = step_w
            routed += 1
        self._pending_main_tools = still
        return routed

    # --- Pending subgraph tools ---

    def buffer_subgraph_tool(
        self,
        *,
        ns_key: tuple[str, ...],
        lookup_id: str,
        display_key: str,
        tool_name: str,
        args: dict[str, Any],
        raw_args: str = "",
    ) -> None:
        """Queue a subgraph tool until namespace → parent resolves."""
        tcid = str(lookup_id).strip()
        if not tcid:
            return
        self._pending_subgraph_tools.append(
            PendingSubgraphTool(
                ns_key=ns_key,
                lookup_id=tcid,
                display_key=display_key,
                tool_name=tool_name or "tool",
                args=dict(args or {}),
                raw_args=raw_args,
            )
        )

    def pending_subgraph_tools(self) -> list[PendingSubgraphTool]:
        """Snapshot of subgraph tools still awaiting parent resolution."""
        return list(self._pending_subgraph_tools)

    @property
    def pending_main_tool_count(self) -> int:
        """Number of root tools still awaiting step card routing."""
        return len(self._pending_main_tools)

    def take_routed_subgraph_tools(
        self,
        routed_display_keys: set[str],
    ) -> None:
        """Remove subgraph pending entries that were mounted (by ``display_key``)."""
        if not routed_display_keys:
            return
        self._pending_subgraph_tools = [
            p for p in self._pending_subgraph_tools if p.display_key not in routed_display_keys
        ]

    def clear_step_tool_bindings(self, step_id: str) -> None:
        """Remove tool→step entries pointing at a completed step."""
        sid = step_id.strip()
        if not sid:
            return
        for tcid, bound in list(self.tool_call_to_step_id.items()):
            if bound == sid:
                self.tool_call_to_step_id.pop(tcid, None)


__all__ = [
    "ParentWidget",
    "PendingMainTool",
    "PendingSubgraphTool",
    "StepTaskRouter",
    "StepWidget",
]
