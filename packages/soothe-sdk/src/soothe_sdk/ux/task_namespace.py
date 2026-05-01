"""FIFO Task-tool namespace binding (IG-334) — reusable pure helpers.

Main graph records ``task`` tool calls in order; first unseen subgraph namespace
binds to the next queued spawn so subgraph streams can recover
``(task_tool_call_id, subagent_type)``.
"""

from __future__ import annotations

from collections import deque
from typing import Any


def enqueue_task_spawn(
    queue: deque[tuple[str, str]],
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
    queue.append((tool_call_id, subagent_type or "?"))


def maybe_bind_namespace(
    bindings: dict[tuple[str, ...], tuple[str, str]],
    queue: deque[tuple[str, str]],
    namespace: tuple[str, ...],
) -> None:
    """Bind ``namespace`` to the next queued spawn if unseen and queue non-empty."""
    if not namespace:
        return
    if namespace in bindings:
        return
    if queue:
        bindings[namespace] = queue.popleft()


def resolve_task_scope_for_namespace(
    bindings: dict[tuple[str, ...], tuple[str, str]],
    namespace: tuple[str, ...],
) -> tuple[str, str] | None:
    """Return ``(task_tool_call_id, subagent_type)`` for stream ``namespace``."""
    if not namespace:
        return None
    for length in range(len(namespace), 0, -1):
        prefix = namespace[:length]
        bound = bindings.get(prefix)
        if bound is not None:
            return bound
    return None


__all__ = [
    "enqueue_task_spawn",
    "maybe_bind_namespace",
    "resolve_task_scope_for_namespace",
]
