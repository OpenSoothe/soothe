"""Task-tool namespace binding — pure helpers for subgraph stream routing.

Main graph records ``task`` tool calls in order; subgraph namespaces bind to spawns
via an unscoped FIFO deferred until :func:`register_task_spawn_for_step` runs
(parallel-safe). Clients without step ids fall back to binding against the spawn queue.

IG-416: Unified tool call ID format for step-level and task-level tool calls.
"""

from __future__ import annotations

from collections import deque
from typing import Any, TypeAlias

TaskScope: TypeAlias = tuple[str, str, str]
"""``(task_tool_call_id, subagent_type, step_id)`` — ``step_id`` may be empty."""

_TASK_SCOPE_SEP = "\x1e"


def _shorten_tool_call_id(raw_tid: str) -> str:
    """Shorten provider tool_call_id for compact display.

    Strips 'functions.' prefix.

    Examples:
        'functions.task:0' → 'task:0'
        'functions.read_file:18' → 'read_file:18'
        'call_abc123' → 'call_abc123' (no pattern match, return as-is)
    """
    tid = str(raw_tid).strip()
    if tid.startswith("functions."):
        tid = tid[len("functions.") :]
    return tid


def parse_unified_tool_call_id(tool_call_id: str) -> tuple[str, str, int | None, str]:
    """Parse unified tool_call_id format into components.

    IG-416: Unified formats encode step_id directly:
    - Step-level: {step_id}:s:{tool}.{idx} (e.g., 'GHT-01:s:task.0')
    - Task-level: {step_id}:t{task_idx}:{tool}.{idx} (e.g., 'GHT-01:t0:read_file.1')

    Args:
        tool_call_id: Unified tool_call_id string.

    Returns:
        Tuple of (step_id, type_code, task_idx, tool_info):
        - step_id: Step identifier (empty if not unified format)
        - type_code: 's' for step-level, 't' for task-level, '' if not unified
        - task_idx: None for step-level, integer for task-level
        - tool_info: Tool name and index part (e.g., 'task.0')

    Examples:
        >>> parse_unified_tool_call_id("GHT-01:s:task.0")
        ('GHT-01', 's', None, 'task.0')
        >>> parse_unified_tool_call_id("GHT-01:t0:read_file.1")
        ('GHT-01', 't', 0, 'read_file.1')
        >>> parse_unified_tool_call_id("task:0")
        ('', '', None, 'task:0')
    """
    tid = str(tool_call_id).strip()
    if not tid:
        return ("", "", None, "")

    # Check for unified format pattern: {step_id}:{type}:{tool_info}
    # Type can be 's' (step) or 't{idx}' (task with index)
    parts = tid.split(":")
    if len(parts) < 3:
        # Not unified format, return as-is
        return ("", "", None, tid)

    step_id = parts[0]
    type_part = parts[1]
    tool_info = parts[2]

    if type_part == "s":
        # Step-level: {step_id}:s:{tool}.{idx}
        return (step_id, "s", None, tool_info)
    elif type_part.startswith("t") and len(type_part) > 1:
        # Task-level: {step_id}:t{task_idx}:{tool}.{idx}
        try:
            task_idx = int(type_part[1:])
            return (step_id, "t", task_idx, tool_info)
        except ValueError:
            # Invalid task index, treat as non-unified
            return ("", "", None, tid)

    # Unknown type code, treat as non-unified
    return ("", "", None, tid)


def task_scope_step_id(scope: TaskScope | None) -> str:
    """Return the AgentLoop step id from a task scope tuple, if present."""
    if not scope:
        return ""
    return str(scope[2] or "").strip()


def task_scope_task_idx(scope: TaskScope | None, step_id: str) -> int:
    """Derive task index within a step from TaskScope and spawns_by_step tracking.

    Returns 0 by default (first task in step).
    """
    if not scope:
        return 0
    # Could be enhanced to track actual task ordering per step
    return 0


def scoped_subgraph_tool_key(
    namespace: tuple[str, ...],
    tool_call_id: str,
    *,
    task_scope: TaskScope | None = None,
) -> str:
    """Build unified tool call ID for subgraph (task-level) tool rows.

    IG-416: Unified format: {step_id}:t{task_idx}:{tool}

    Args:
        namespace: LangGraph subgraph namespace tuple.
        tool_call_id: Provider tool call id.
        task_scope: Optional resolved TaskScope for step_id extraction.

    Returns:
        Unified tool call ID; empty namespace returns shortened tool_call_id.
    """
    short_tid = _shorten_tool_call_id(tool_call_id)
    if not namespace:
        return short_tid

    # Extract step_id from task_scope if available
    step_id = task_scope_step_id(task_scope) if task_scope else ""
    task_idx = task_scope_task_idx(task_scope, step_id) if task_scope else 0

    if step_id:
        # Unified format: {step_id}:t{task_idx}:{tool}
        return f"{step_id}:t{task_idx}:{short_tid}"

    # Fallback: use namespace hash for uniqueness when step_id unknown
    ns = "/".join(str(p) for p in namespace)
    return f"{ns}{_TASK_SCOPE_SEP}{short_tid}"


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
    "_shorten_tool_call_id",
    "enqueue_task_spawn",
    "maybe_bind_namespace",
    "parse_unified_tool_call_id",
    "register_task_spawn_for_step",
    "resolve_task_parent_lookup",
    "resolve_task_scope_for_namespace",
    "scoped_subgraph_tool_key",
    "task_scope_step_id",
    "task_scope_task_idx",
]
