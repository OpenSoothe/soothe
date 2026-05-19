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
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
    register_task_spawn_for_step,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    task_scope_step_id,
    try_bind_namespace_to_unlinked_spawn,
)

StepWidget: TypeAlias = Any
"""``CognitionStepMessage`` or compatible step card (duck-typed)."""

ParentWidget: TypeAlias = Any
"""Step card parent for tool stats and subagent activity."""


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
    """

    active_step_ids: set[str] = field(default_factory=set)

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

    def step_id_for_tool(self, tool_call_id: str) -> str:
        """Return execute step id encoded in a unified root tool_call_id."""
        parsed_sid, _, _, _ = parse_unified_tool_call_id(str(tool_call_id).strip())
        return parsed_sid

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
        try_bind_namespace_to_unlinked_spawn(
            self._namespace_bindings,
            self._spawns_by_step_id,
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
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(tcid)
        sid = parsed_sid if (parsed_sid and type_code == "s") else ""
        if not sid:
            sid = str(step_id).strip()
        if not sid:
            return False
        normalized_tcid = normalize_step_task_tool_call_id(sid, tcid)
        spawn_key = (sid, normalized_tcid)
        if spawn_key in self._spawn_recorded:
            return False
        scope: TaskScope = (
            normalized_tcid,
            (subagent_type or "?").strip() or "?",
            sid,
        )
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
            if not bound and len(self.active_step_ids) == 1:
                bound = next(iter(self.active_step_ids))
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
                display_key=display_key or tcid,
                tool_name=tool_name or "tool",
                args=dict(args or {}),
                raw_args=raw_args,
            )
        )

    def _ingest_subgraph_tool_on_parent(
        self,
        item: PendingSubgraphTool,
        parent: ParentWidget,
        scope: TaskScope,
        tool_to_step: dict[str, ParentWidget],
    ) -> bool:
        """Register one subgraph tool row on an already-resolved parent step card."""
        row_id = str(item.display_key or item.lookup_id).strip()
        if not row_id:
            return False
        ingest = getattr(parent, "add_tool_call", None)
        if not callable(ingest):
            return False
        has_row = getattr(parent, "has_tool_call_row", lambda _x: False)
        if has_row(row_id):
            update = getattr(parent, "update_tool_args", None)
            if callable(update):
                update(row_id, item.args)
        else:
            parent_task_id = str(scope[0]).strip()
            ingest(
                row_id,
                item.tool_name,
                dict(item.args or {}),
                raw_args=item.raw_args,
                parent_tool_call_id=parent_task_id or None,
            )
        tool_to_step[row_id] = parent
        return True

    def try_route_subgraph_tool(
        self,
        *,
        ns_key: tuple[str, ...],
        lookup_id: str,
        display_key: str,
        tool_name: str,
        args: dict[str, Any],
        raw_args: str = "",
        step_cards: dict[str, StepWidget],
        tool_to_step: dict[str, ParentWidget],
        tool_display_by_call_id: dict[str, ParentWidget],
    ) -> bool:
        """Attach a subgraph tool to its parent step card for running-line stats.

        Returns:
            True when the tool was ingested on a step card; False when buffered.
        """
        item = PendingSubgraphTool(
            ns_key=ns_key,
            lookup_id=str(lookup_id).strip(),
            display_key=display_key or str(lookup_id).strip(),
            tool_name=tool_name or "tool",
            args=dict(args or {}),
            raw_args=raw_args,
        )
        if not item.lookup_id:
            return False
        scope = self.resolve_task_scope(ns_key)
        if scope is None:
            self._pending_subgraph_tools.append(item)
            return False
        parent = self.resolve_parent(
            scope,
            step_cards=step_cards,
            tool_display_by_call_id=tool_display_by_call_id,
        )
        if parent is None:
            self._pending_subgraph_tools.append(item)
            return False
        return self._ingest_subgraph_tool_on_parent(item, parent, scope, tool_to_step)

    def route_pending_subgraph_tools(
        self,
        step_cards: dict[str, StepWidget],
        tool_to_step: dict[str, ParentWidget],
        tool_display_by_call_id: dict[str, ParentWidget],
    ) -> int:
        """Attach buffered subgraph tools when namespace bindings exist.

        Returns:
            Number of tools routed out of the pending buffer.
        """
        if not self._pending_subgraph_tools:
            return 0
        still: list[PendingSubgraphTool] = []
        routed = 0
        for item in self._pending_subgraph_tools:
            scope = self.resolve_task_scope(item.ns_key)
            if scope is None:
                still.append(item)
                continue
            parent = self.resolve_parent(
                scope,
                step_cards=step_cards,
                tool_display_by_call_id=tool_display_by_call_id,
            )
            if parent is None:
                still.append(item)
                continue
            if self._ingest_subgraph_tool_on_parent(item, parent, scope, tool_to_step):
                routed += 1
            else:
                still.append(item)
        self._pending_subgraph_tools = still
        return routed

    def pending_subgraph_tools(self) -> list[PendingSubgraphTool]:
        """Snapshot of subgraph tools still awaiting parent resolution."""
        return list(self._pending_subgraph_tools)

    @property
    def pending_main_tool_count(self) -> int:
        """Number of root tools still awaiting step card routing."""
        return len(self._pending_main_tools)

    def clear_step_tool_bindings(self, step_id: str) -> None:
        """No-op: step routing uses unified tool_call_id encoding only."""
        _ = step_id


__all__ = [
    "ParentWidget",
    "PendingMainTool",
    "PendingSubgraphTool",
    "StepTaskRouter",
    "StepWidget",
]
