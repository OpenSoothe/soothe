"""FIFO Task-tool namespace binding (IG-334) — reusable pure helpers.

Main graph records ``task`` tool calls in order; subgraph namespaces bind to the
spawn for the **active execute step** (from ``AGENT_LOOP_STEP_TOOL_BINDING``) when
available, otherwise FIFO queue fallback for non-loop clients.

Parallel waves may reuse the same provider ``tool_call_id`` (e.g. ``functions.task:0``);
``step_id`` disambiguates spawns and parent step cards.
"""

from __future__ import annotations

from collections import deque
from typing import Any, TypeAlias

TaskScope: TypeAlias = tuple[str, str, str]
"""``(task_tool_call_id, subagent_type, step_id)`` — ``step_id`` may be empty."""

_TASK_SCOPE_SEP = "\x1e"


def task_scope_step_id(scope: TaskScope | tuple[str, str] | None) -> str:
    """Return the AgentLoop step id from a task scope tuple, if present."""
    if not scope:
        return ""
    if len(scope) >= 3:
        return str(scope[2] or "").strip()
    return ""


def normalize_task_scope(scope: TaskScope | tuple[str, str] | None) -> TaskScope | None:
    """Normalize legacy 2-tuples to ``TaskScope``."""
    if not scope:
        return None
    if len(scope) >= 3:
        return (str(scope[0]), str(scope[1]), str(scope[2] or ""))
    if len(scope) == 2:
        return (str(scope[0]), str(scope[1]), "")
    return None


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
    step_id: str = "",
) -> None:
    """Queue a Task delegation when ``tool_name`` is ``task`` on the main graph."""
    if not is_main or tool_name != "task" or not tool_call_id:
        return
    raw = args.get("subagent_type", "")
    subagent_type = raw.strip() if isinstance(raw, str) else ""
    queue.append((tool_call_id, subagent_type or "?", str(step_id or "").strip()))


def register_task_spawn_for_step(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    spawns_by_step: dict[str, TaskScope],
    pending_namespaces_by_step: dict[str, list[tuple[str, ...]]],
    scope: TaskScope,
) -> None:
    """Record a task spawn for ``scope[2]`` and bind any namespaces that arrived early.

    Args:
        bindings: LangGraph namespace → task scope map (updated in place).
        queue: FIFO fallback queue (also appended for headless CLI parity).
        spawns_by_step: Authoritative ``step_id`` → spawn map for AgentLoop execute.
        pending_namespaces_by_step: Namespaces seen before spawn for that step.
        scope: ``(tool_call_id, subagent_type, step_id)``.
    """
    queue.append(scope)
    step_id = task_scope_step_id(scope)
    if not step_id:
        return
    spawns_by_step[step_id] = scope
    for ns in pending_namespaces_by_step.pop(step_id, []):
        if ns not in bindings:
            bindings[ns] = scope


def maybe_bind_namespace(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    namespace: tuple[str, ...],
    *,
    active_step_id: str = "",
    spawns_by_step: dict[str, TaskScope] | None = None,
    pending_namespaces_by_step: dict[str, list[tuple[str, ...]]] | None = None,
) -> None:
    """Bind ``namespace`` to the task spawn for the active step, else FIFO queue.

    When ``active_step_id`` is set (TUI: from ``AGENT_LOOP_STEP_TOOL_BINDING``) and the
    spawn for that step is already registered, bind immediately. If the spawn is not
    registered yet, defer the namespace until :func:`register_task_spawn_for_step` runs.
    """
    if not namespace:
        return
    if namespace in bindings:
        return
    step_id = (active_step_id or "").strip()
    if step_id and spawns_by_step is not None and step_id in spawns_by_step:
        bindings[namespace] = spawns_by_step[step_id]
        return
    if step_id and pending_namespaces_by_step is not None:
        pending_namespaces_by_step.setdefault(step_id, []).append(namespace)
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
    scope: TaskScope | tuple[str, str] | None,
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
    norm = normalize_task_scope(scope)
    if norm is None:
        return None
    step_id = task_scope_step_id(norm)
    if step_id:
        parent = step_cards.get(step_id)
        if parent is not None:
            return parent
    return tool_display_by_call_id.get(norm[0])


__all__ = [
    "TaskScope",
    "enqueue_task_spawn",
    "maybe_bind_namespace",
    "normalize_task_scope",
    "register_task_spawn_for_step",
    "resolve_task_parent_lookup",
    "resolve_task_scope_for_namespace",
    "scoped_subgraph_tool_key",
    "task_scope_step_id",
]
