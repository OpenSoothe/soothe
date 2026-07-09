"""Per-turn routing for StrangeLoop steps, root tools, and subagent task namespaces.

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
    is_inner_subgraph_task_tool_id,
    normalize_main_task_delegation_id,
    parse_unified_tool_call_id,
    prune_bound_pending_namespaces,
    register_task_spawn_for_step,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    row_key_for_subgraph_tool,
    task_scope_step_id,
    try_bind_namespace_from_tool_call_id,
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


def _subgraph_pending_key(ns_key: tuple[str, ...], lookup_id: str) -> tuple[tuple[str, ...], str]:
    """Stable key for coalescing repeated stream chunks for one logical subgraph tool."""
    return (ns_key, str(lookup_id).strip())


def _is_task_metadata_subgraph_tool(item: PendingSubgraphTool) -> bool:
    """True when a buffered subgraph item is task metadata, not a user-facing tool row."""
    if (item.tool_name or "").strip() == "task":
        return True
    for candidate in (item.lookup_id, item.display_key):
        cid = str(candidate or "").strip()
        if cid and is_inner_subgraph_task_tool_id(cid):
            return True
    args = item.args if isinstance(item.args, dict) else {}
    subagent_type = str(args.get("subagent_type") or "").strip()
    prompt = str(args.get("description") or args.get("prompt") or "").strip()
    # Some providers emit opaque names (e.g. "tool-<id>") for task chunks.
    return bool(subagent_type and prompt)


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
    _spawns_by_task_id: dict[str, TaskScope] = field(default_factory=dict, repr=False)
    _pending_unscoped_namespaces: deque[tuple[str, ...]] = field(default_factory=deque, repr=False)
    _spawn_recorded: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _pending_main_tools: dict[str, PendingMainTool] = field(default_factory=dict, repr=False)
    _pending_subgraph_tools: dict[tuple[tuple[str, ...], str], PendingSubgraphTool] = field(
        default_factory=dict,
        repr=False,
    )

    def reset_turn(self) -> None:
        """Clear all per-turn routing state."""
        self.active_step_ids.clear()
        self._task_spawn_queue.clear()
        self._namespace_bindings.clear()
        self._spawns_by_step_id.clear()
        self._spawns_by_task_id.clear()
        self._pending_unscoped_namespaces.clear()
        self._spawn_recorded.clear()
        self._pending_main_tools.clear()
        self._pending_subgraph_tools.clear()

    def _upsert_pending_main_tool(self, item: PendingMainTool) -> None:
        """Merge streaming updates for the same root tool_call_id."""
        key = str(item.tool_call_id).strip()
        if not key:
            return
        existing = self._pending_main_tools.get(key)
        if existing is None:
            self._pending_main_tools[key] = item
            return
        args = item.args if len(item.args) >= len(existing.args) else existing.args
        raw = item.raw_args if len(item.raw_args) >= len(existing.raw_args) else existing.raw_args
        self._pending_main_tools[key] = PendingMainTool(
            tool_call_id=key,
            name=item.name or existing.name,
            args=args,
            raw_args=raw,
        )

    def _upsert_pending_subgraph_tool(self, item: PendingSubgraphTool) -> None:
        """Merge streaming updates for the same subgraph namespace + tool_call_id."""
        key = _subgraph_pending_key(item.ns_key, item.lookup_id)
        if not key[1]:
            return
        existing = self._pending_subgraph_tools.get(key)
        if existing is None:
            self._pending_subgraph_tools[key] = item
            return
        # Prefer meaningful args over placeholder metadata like {"_subgraph_tool": true}.
        from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict

        item_meaningful = extract_tool_args_dict(item.args or {})
        existing_meaningful = extract_tool_args_dict(existing.args or {})
        if len(item_meaningful) >= len(existing_meaningful):
            args = item.args
        else:
            args = existing.args
        raw = item.raw_args if len(item.raw_args) >= len(existing.raw_args) else existing.raw_args
        self._pending_subgraph_tools[key] = PendingSubgraphTool(
            ns_key=item.ns_key,
            lookup_id=key[1],
            display_key=item.display_key or existing.display_key,
            tool_name=item.tool_name or existing.tool_name,
            args=args,
            raw_args=raw,
        )

    # --- Step lifecycle ---

    def on_step_started(self, step_id: str) -> None:
        """Track a step entering the running phase."""
        sid = step_id.strip()
        if sid:
            self.active_step_ids.add(sid)

    def maybe_promote_step_to_running(
        self,
        step_w: StepWidget,
        tool_call_id: str,
        *,
        step_cards: dict[str, StepWidget],
    ) -> None:
        """Promote a pending step card to running only when it is executing (RFC-628).

        Future steps are not pre-mounted in the message list; only the active step
        may transition to ``running`` before ``step.started`` when tools arrive early.
        """
        if getattr(step_w, "_status", "") != "pending":
            return
        step_id = str(getattr(step_w, "_step_id", "") or "").strip()
        if not step_id:
            return

        tcid = str(tool_call_id or "").strip()
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid and parsed_sid != step_id:
            return

        if step_id in self.active_step_ids:
            allowed = True
        elif self.active_step_ids:
            allowed = False
        else:
            allowed = not any(
                getattr(w, "_status", "") == "running"
                and str(getattr(w, "_step_id", "") or "").strip() != step_id
                for w in step_cards.values()
            )

        if not allowed:
            return
        promote = getattr(step_w, "promote_to_running_if_pending", None)
        if callable(promote):
            promote()

    def on_step_completed(self, step_id: str) -> None:
        """Drop step from the active set and spawn registry."""
        sid = step_id.strip()
        if sid:
            self.active_step_ids.discard(sid)
            removed = self._spawns_by_step_id.pop(sid, None)
            if removed is not None:
                self._spawns_by_task_id.pop(str(removed[0]).strip(), None)
            drop_tcid = [
                tcid
                for tcid, scope in self._spawns_by_task_id.items()
                if task_scope_step_id(scope) == sid
            ]
            for tcid in drop_tcid:
                self._spawns_by_task_id.pop(tcid, None)

    def step_id_for_tool(self, tool_call_id: str) -> str:
        """Return execute step id encoded in a unified root tool_call_id."""
        parsed_sid, _, _, _ = parse_unified_tool_call_id(str(tool_call_id).strip())
        return parsed_sid

    # --- Namespace / task spawn ---

    def on_subgraph_namespace(self, namespace: tuple[str, ...]) -> None:
        """Defer subgraph namespace for unified ID-based binding from tool_call_ids."""
        if not namespace:
            return
        if namespace in self._namespace_bindings:
            return
        if namespace not in self._pending_unscoped_namespaces:
            self._pending_unscoped_namespaces.append(namespace)
        # Bind using unified step ids from pending subgraph tool buffers
        self._try_bind_namespaces_from_pending_tools()
        prune_bound_pending_namespaces(
            self._namespace_bindings,
            self._pending_unscoped_namespaces,
        )

    def _try_bind_namespaces_from_pending_tools(self) -> int:
        """Bind deferred namespaces using unified step ids from buffered subgraph tools."""
        bound = 0
        for item in list(self._pending_subgraph_tools.values()):
            for candidate in (item.display_key, item.lookup_id):
                cand = str(candidate or "").strip()
                if not cand:
                    continue
                if try_bind_namespace_from_tool_call_id(
                    self._namespace_bindings,
                    self._spawns_by_step_id,
                    item.ns_key,
                    cand,
                    spawns_by_task_id=self._spawns_by_task_id,
                ):
                    bound += 1
                    try:
                        self._pending_unscoped_namespaces.remove(item.ns_key)
                    except ValueError:
                        pass
                    break
        return bound

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
        if not tcid or is_inner_subgraph_task_tool_id(tcid):
            return False
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(tcid)
        sid = parsed_sid if (parsed_sid and type_code in ("s", "t")) else ""
        if not sid:
            sid = str(step_id).strip()
        if not sid:
            return False
        normalized_tcid = normalize_main_task_delegation_id(sid, tcid, tool_name="task")
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
            spawns_by_task_id=self._spawns_by_task_id,
        )
        self._spawn_recorded.add(spawn_key)
        prune_bound_pending_namespaces(
            self._namespace_bindings,
            self._pending_unscoped_namespaces,
        )
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
        self._upsert_pending_main_tool(
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
        still: dict[str, PendingMainTool] = {}
        routed = 0
        for key, item in self._pending_main_tools.items():
            bound = self.step_id_for_tool(item.tool_call_id)
            if not bound and len(self.active_step_ids) == 1:
                bound = next(iter(self.active_step_ids))
            if not bound:
                still[key] = item
                continue
            step_w = step_cards.get(bound)
            if step_w is None:
                still[key] = item
                continue
            ingest = getattr(step_w, "add_tool_call", None)
            if not callable(ingest):
                still[key] = item
                continue
            if not getattr(step_w, "has_tool_call_row", lambda _x: False)(item.tool_call_id):
                ingest(
                    item.tool_call_id,
                    item.name,
                    item.args,
                    raw_args=item.raw_args,
                )
                self.maybe_promote_step_to_running(
                    step_w,
                    item.tool_call_id,
                    step_cards=step_cards,
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
        self._upsert_pending_subgraph_tool(
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
        *,
        step_cards: dict[str, StepWidget] | None = None,
    ) -> bool:
        """Register one subgraph tool row on an already-resolved parent step card."""
        if _is_task_metadata_subgraph_tool(item):
            # Inner subagent ``task`` chunks are not user-facing tool stats; ingesting
            # them used to rewrite the main ``{step}:s:task:…`` delegation row args.
            return True
        display = str(item.display_key or "").strip()
        _, display_type, _, _ = parse_unified_tool_call_id(display)
        if display_type == "t":
            row_id = display
        else:
            row_id = row_key_for_subgraph_tool(
                item.ns_key,
                item.lookup_id,
                task_scope=scope,
            )
            row_id = str(row_id or display or item.lookup_id).strip()
        if not row_id:
            return False
        ingest = getattr(parent, "add_tool_call", None)
        if not callable(ingest):
            return False
        has_row = getattr(parent, "has_tool_call_row", lambda _x: False)
        if has_row(row_id):
            update = getattr(parent, "update_tool_args", None)
            if callable(update):
                resolved_args = dict(item.args or {})
                # Placeholder args like {"_subgraph_tool": true} are not meaningful.
                # Parse raw_args when resolved_args lacks real invocation kwargs.
                from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict

                meaningful_args = extract_tool_args_dict(resolved_args)
                if item.raw_args and not meaningful_args:
                    parsed = extract_tool_args_dict({"_raw": item.raw_args})
                    if parsed:
                        resolved_args = parsed
                update(row_id, resolved_args)
        else:
            resolved_args = dict(item.args or {})
            from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict

            meaningful_args = extract_tool_args_dict(resolved_args)
            if item.raw_args and not meaningful_args:
                parsed = extract_tool_args_dict({"_raw": item.raw_args})
                if parsed:
                    resolved_args = parsed
            ingest(
                row_id,
                item.tool_name,
                resolved_args,
                raw_args=item.raw_args,
            )
        tool_to_step[row_id] = parent
        if step_cards is not None:
            self.maybe_promote_step_to_running(parent, row_id, step_cards=step_cards)
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
        for candidate in (item.lookup_id, item.display_key):
            cand = str(candidate or "").strip()
            if not cand:
                continue
            if try_bind_namespace_from_tool_call_id(
                self._namespace_bindings,
                self._spawns_by_step_id,
                ns_key,
                cand,
                spawns_by_task_id=self._spawns_by_task_id,
            ):
                try:
                    self._pending_unscoped_namespaces.remove(ns_key)
                except ValueError:
                    pass
                break
        scope = self.resolve_task_scope(ns_key)
        if scope is not None:
            _, display_type, _, _ = parse_unified_tool_call_id(item.display_key)
            if display_type != "t":
                recomputed = row_key_for_subgraph_tool(ns_key, item.lookup_id, task_scope=scope)
                if recomputed:
                    item.display_key = recomputed
        if self._namespace_bindings:
            self.route_pending_subgraph_tools(
                step_cards,
                tool_to_step,
                tool_display_by_call_id,
            )
        scope = self.resolve_task_scope(ns_key)
        if scope is None:
            self._upsert_pending_subgraph_tool(item)
            return False
        parent = self.resolve_parent(
            scope,
            step_cards=step_cards,
            tool_display_by_call_id=tool_display_by_call_id,
        )
        if parent is None:
            self._upsert_pending_subgraph_tool(item)
            return False
        pending_key = _subgraph_pending_key(ns_key, item.lookup_id)
        self._pending_subgraph_tools.pop(pending_key, None)
        return self._ingest_subgraph_tool_on_parent(
            item,
            parent,
            scope,
            tool_to_step,
            step_cards=step_cards,
        )

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
        still: dict[tuple[tuple[str, ...], str], PendingSubgraphTool] = {}
        routed = 0
        for key, item in self._pending_subgraph_tools.items():
            for candidate in (item.display_key, item.lookup_id):
                cand = str(candidate or "").strip()
                if not cand:
                    continue
                if try_bind_namespace_from_tool_call_id(
                    self._namespace_bindings,
                    self._spawns_by_step_id,
                    item.ns_key,
                    cand,
                    spawns_by_task_id=self._spawns_by_task_id,
                ):
                    try:
                        self._pending_unscoped_namespaces.remove(item.ns_key)
                    except ValueError:
                        pass
                    break
            scope = self.resolve_task_scope(item.ns_key)
            if scope is None:
                still[key] = item
                continue
            _, display_type, _, _ = parse_unified_tool_call_id(item.display_key)
            if display_type != "t":
                recomputed = row_key_for_subgraph_tool(
                    item.ns_key, item.lookup_id, task_scope=scope
                )
                if recomputed:
                    item.display_key = recomputed
            parent = self.resolve_parent(
                scope,
                step_cards=step_cards,
                tool_display_by_call_id=tool_display_by_call_id,
            )
            if parent is None:
                still[key] = item
                continue
            if self._ingest_subgraph_tool_on_parent(
                item,
                parent,
                scope,
                tool_to_step,
                step_cards=step_cards,
            ):
                routed += 1
            else:
                still[key] = item
        self._pending_subgraph_tools = still
        return routed

    def pending_subgraph_tools(self) -> list[PendingSubgraphTool]:
        """Snapshot of subgraph tools still awaiting parent resolution."""
        return list(self._pending_subgraph_tools.values())

    def discard_pending_subgraph_tool(self, ns_key: tuple[str, ...], lookup_id: str) -> None:
        """Drop a buffered subgraph tool after routing it to a SubAgent card."""
        self._pending_subgraph_tools.pop(_subgraph_pending_key(ns_key, lookup_id), None)

    @property
    def pending_main_tool_count(self) -> int:
        """Number of root tools still awaiting step card routing."""
        return len(self._pending_main_tools)


__all__ = [
    "ParentWidget",
    "PendingMainTool",
    "PendingSubgraphTool",
    "StepTaskRouter",
    "StepWidget",
]
