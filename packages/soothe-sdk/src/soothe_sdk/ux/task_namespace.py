"""Task-tool namespace binding — pure helpers for subgraph stream routing.

Main graph records ``task`` tool calls in order; subgraph namespaces bind to spawns
via an unscoped FIFO deferred until :func:`register_task_spawn_for_step` runs
(parallel-safe). Clients without step ids fall back to binding against the spawn queue.
"""

from __future__ import annotations

from collections import deque
from typing import Any, TypeAlias

TaskScope: TypeAlias = tuple[str, str, str]
"""``(task_tool_call_id, subagent_type, step_id)`` — ``step_id`` may be empty."""

_TASK_SCOPE_SEP = "\x1e"


def task_scope_step_id(scope: TaskScope | None) -> str:
    """Return the AgentLoop step id from a task scope tuple, if present."""
    if not scope:
        return ""
    return str(scope[2] or "").strip()


def scoped_subgraph_tool_key(namespace: tuple[str, ...], tool_call_id: str) -> str:
    """Build a turn-unique key for subgraph tool rows (parallel-safe).

    Args:
        namespace: LangGraph subgraph namespace tuple.
        tool_call_id: Provider tool call id (often reused across branches).

    Returns:
        Opaque string key; empty namespace returns ``tool_call_id`` unchanged.
    """
    tcid = str(tool_call_id).strip()
    if not namespace:
        return tcid
    ns = "/".join(str(p) for p in namespace)
    return f"{ns}{_TASK_SCOPE_SEP}{tcid}"


def enqueue_task_spawn(
    queue: deque[TaskScope],
    *,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str,
    is_main: bool,
) -> None:
    """Queue a Task delegation when ``tool_name`` is ``task`` on the main graph."""
    if not is_main or tool_name != "task" or not tool_call_id:
        return
    raw = args.get("subagent_type", "")
    subagent_type = raw.strip() if isinstance(raw, str) else ""
    queue.append((tool_call_id, subagent_type or "?", ""))


def register_task_spawn_for_step(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    spawns_by_step: dict[str, TaskScope],
    scope: TaskScope,
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
) -> None:
    """Record a task spawn for ``scope[2]`` and bind any namespaces that arrived early.

    Args:
        bindings: LangGraph namespace → task scope map (updated in place).
        queue: FIFO fallback queue (also appended for headless clients).
        spawns_by_step: Authoritative ``step_id`` → spawn map for AgentLoop execute.
        scope: ``(tool_call_id, subagent_type, step_id)``.
        pending_unscoped_namespaces: FIFO of namespaces seen before spawn (parallel-safe).
    """
    queue.append(scope)
    step_id = task_scope_step_id(scope)
    if not step_id:
        return
    spawns_by_step[step_id] = scope
    if pending_unscoped_namespaces is not None:
        while pending_unscoped_namespaces:
            ns = pending_unscoped_namespaces.popleft()
            if ns not in bindings:
                bindings[ns] = scope
                break


def maybe_bind_namespace(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    namespace: tuple[str, ...],
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
) -> None:
    """Defer ``namespace`` until a spawn is registered, or bind via the spawn queue.

    When ``pending_unscoped_namespaces`` is provided (TUI / AgentLoop), namespaces are
    queued in arrival order and consumed one per :func:`register_task_spawn_for_step`.
    Otherwise the next queued main-graph ``task`` spawn is bound immediately (headless).
    """
    if not namespace or namespace in bindings:
        return
    if pending_unscoped_namespaces is not None:
        pending_unscoped_namespaces.append(namespace)
        return
    if queue:
        bindings[namespace] = queue.popleft()


def resolve_task_scope_for_namespace(
    bindings: dict[tuple[str, ...], TaskScope],
    namespace: tuple[str, ...],
) -> TaskScope | None:
    """Return task scope for stream ``namespace``."""
    if not namespace:
        return None
    for length in range(len(namespace), 0, -1):
        prefix = namespace[:length]
        bound = bindings.get(prefix)
        if bound is not None:
            return bound
    return None


def resolve_task_parent_lookup(
    scope: TaskScope | None,
    *,
    step_cards: dict[str, Any],
    tool_display_by_call_id: dict[str, Any],
) -> Any | None:
    """Resolve the UI parent card for a task scope (step card preferred).

    Args:
        scope: Task scope from :func:`resolve_task_scope_for_namespace`.
        step_cards: ``step_id`` → step widget (e.g. ``CognitionStepMessage``).
        tool_display_by_call_id: Fallback ``tool_call_id`` → card map.

    Returns:
        Parent widget, or ``None`` when unresolved.
    """
    if scope is None:
        return None
    step_id = task_scope_step_id(scope)
    if step_id:
        parent = step_cards.get(step_id)
        if parent is not None:
            return parent
    return tool_display_by_call_id.get(scope[0])


__all__ = [
    "TaskScope",
    "enqueue_task_spawn",
    "maybe_bind_namespace",
    "register_task_spawn_for_step",
    "resolve_task_parent_lookup",
    "resolve_task_scope_for_namespace",
    "scoped_subgraph_tool_key",
    "task_scope_step_id",
]
