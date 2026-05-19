"""Task-tool namespace binding — pure helpers for subgraph stream routing.

Main graph records ``task`` tool calls in order; subgraph namespaces bind to spawns
via an unscoped FIFO deferred until :func:`register_task_spawn_for_step` runs
(parallel-safe). Clients without step ids fall back to binding against the spawn queue.

IG-416: Unified tool call ID format for step-level and task-level tool calls.
Canonical wire form: ``{step_wire}:s:{tool}:{idx}`` (e.g. ``GHT_01:s:grep:0``).
"""

from __future__ import annotations

from collections import deque
from typing import Any, TypeAlias

TaskScope: TypeAlias = tuple[str, str, str]
"""``(task_tool_call_id, subagent_type, step_id)`` — ``step_id`` may be empty."""

_TASK_SCOPE_SEP = "\x1e"


def _step_id_to_unified_fragment(step_id: str) -> str:
    """Map execute step ids (``GHT-01``) to the unified wire fragment (``GHT_01``)."""
    return str(step_id).strip().replace("-", "_")


def _step_id_from_unified_fragment(fragment: str) -> str:
    """Map unified wire step fragment back to canonical execute step id."""
    return str(fragment).strip().replace("_", "-")


def _is_wire_step_fragment(fragment: str) -> bool:
    """True when the first segment uses underscore wire form (``GHT_01``)."""
    text = str(fragment).strip()
    return bool(text) and "_" in text and "-" not in text


def _provider_tool_fragment(tid: str) -> str:
    """Parse provider ``tool:idx`` into unified ``tool:idx`` fragment."""
    text = str(tid).strip()
    if not text:
        return text
    if ":" in text:
        name, _, idx = text.rpartition(":")
        if name and idx.isdigit():
            return f"{name}:{idx}"
    return text


def _tool_info_from_unified_parts(parts: list[str]) -> str:
    """Extract ``tool:idx`` from colon segments after the type segment."""
    if len(parts) >= 4 and parts[-1].isdigit():
        return f"{parts[-2]}:{parts[-1]}"
    return ""


def _format_unified_tool_call_id(
    step_id: str,
    type_part: str,
    tool_fragment: str,
) -> str:
    """Build canonical unified id: ``{step_wire}:{type}:{tool}:{idx}``."""
    sid_wire = _step_id_to_unified_fragment(step_id)
    frag = _provider_tool_fragment(tool_fragment)
    return f"{sid_wire}:{type_part}:{frag}"


def is_unified_tool_call_id(tool_call_id: str) -> bool:
    """Return True when ``tool_call_id`` matches the canonical unified wire format."""
    step_id, type_code, _, tool_info = parse_unified_tool_call_id(tool_call_id)
    return bool(step_id and type_code in ("s", "t") and tool_info)


def _shorten_tool_call_id(raw_tid: str) -> str:
    """Shorten provider tool_call_id to ``tool:idx`` for unified id assembly.

    Accepts provider ids (``functions.grep:0``). Already-unified ids yield their
    tool fragment via :func:`parse_unified_tool_call_id`.
    """
    tid = str(raw_tid).strip()
    parsed_sid, type_code, _, tool_info = parse_unified_tool_call_id(tid)
    if parsed_sid and type_code in ("s", "t") and tool_info:
        return tool_info
    if tid.startswith("functions."):
        tid = tid[len("functions.") :]
    return _provider_tool_fragment(tid)


def normalize_unified_tool_call_id(tool_call_id: str) -> str:
    """Reformat a canonical unified id; non-unified ids are returned unchanged."""
    tid = str(tool_call_id).strip()
    if not tid:
        return tid
    step_id, type_code, task_idx, tool_info = parse_unified_tool_call_id(tid)
    if not step_id or not type_code or not tool_info:
        return tid
    if type_code == "s":
        return _format_unified_tool_call_id(step_id, "s", tool_info)
    if type_code == "t" and task_idx is not None:
        return _format_unified_tool_call_id(step_id, f"t{task_idx}", tool_info)
    return tid


def parse_unified_tool_call_id(tool_call_id: str) -> tuple[str, str, int | None, str]:
    """Parse unified tool_call_id format into components.

    Canonical wire form (strict):
    - Step-level: ``{step_wire}:s:{tool}:{idx}`` (e.g. ``GHT_01:s:grep:0``)
    - Task-level: ``{step_wire}:t{task_idx}:{tool}:{idx}`` (e.g. ``GHT_01:t0:read_file:1``)

    Args:
        tool_call_id: Unified tool_call_id string.

    Returns:
        Tuple of (step_id, type_code, task_idx, tool_info):
        - step_id: Canonical execute step id (hyphen form, e.g. ``GHT-01``)
        - type_code: ``s`` for step-level, ``t`` for task-level, ``''`` if not unified
        - task_idx: ``None`` for step-level, integer for task-level
        - tool_info: Tool name and index (e.g. ``grep:0``)
    """
    tid = str(tool_call_id).strip()
    if not tid:
        return ("", "", None, "")

    parts = tid.split(":")
    if len(parts) < 4 or not _is_wire_step_fragment(parts[0]):
        return ("", "", None, tid)

    step_id = _step_id_from_unified_fragment(parts[0])
    type_part = parts[1]
    tool_info = _tool_info_from_unified_parts(parts)
    if not tool_info:
        return ("", "", None, tid)

    if type_part == "s":
        return (step_id, "s", None, tool_info)
    if type_part.startswith("t") and len(type_part) > 1:
        try:
            task_idx = int(type_part[1:])
        except ValueError:
            return ("", "", None, tid)
        return (step_id, "t", task_idx, tool_info)

    return ("", "", None, tid)


def is_step_level_task_tool_id(tool_call_id: str) -> bool:
    """True for unified main-graph ``task`` delegation ids (``{step}:s:task:…``)."""
    _, type_code, _, tool_info = parse_unified_tool_call_id(tool_call_id)
    if type_code != "s":
        return False
    return (tool_info or "").split(":")[0] == "task"


def normalize_step_task_tool_call_id(step_id: str, tool_call_id: str) -> str:
    """Return step-scoped unified id for a main-graph ``task`` delegation.

    Args:
        step_id: AgentLoop execute step id.
        tool_call_id: Unified or provider tool call id from the stream.

    Returns:
        ``{step_wire}:s:task:{idx}`` (canonical).
    """
    sid = str(step_id).strip()
    tcid = str(tool_call_id).strip()
    if not sid:
        return tcid
    if is_unified_tool_call_id(tcid):
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid == sid and type_code == "s" and is_step_level_task_tool_id(tcid):
            return normalize_unified_tool_call_id(tcid)
    short = _shorten_tool_call_id(tcid)
    if not short.startswith("task"):
        short = "task:0"
    return _format_unified_tool_call_id(sid, "s", short)


def step_level_parent_task_call_id(step_id: str, task_idx: int | None = None) -> str:
    """Parent ``task`` row id for inner tools under ``{step_wire}:t{idx}:…``."""
    idx = 0 if task_idx is None else int(task_idx)
    return _format_unified_tool_call_id(step_id, "s", f"task:{idx}")


def resolve_step_id_from_subgraph_tool(tool_call_id: str) -> str:
    """Extract execute ``step_id`` from a unified step- or task-level tool call id."""
    step_id, type_code, _, _ = parse_unified_tool_call_id(str(tool_call_id).strip())
    if step_id and type_code in ("s", "t"):
        return step_id
    return ""


def task_scope_step_id(scope: TaskScope | None) -> str:
    """Return the AgentLoop step id from a task scope tuple, if present."""
    if not scope:
        return ""
    return str(scope[2] or "").strip()


def task_scope_task_idx(scope: TaskScope | None, step_id: str) -> int:
    """Derive task index within a step from TaskScope and spawns_by_step tracking."""
    if not scope:
        return 0
    return 0


def resolve_task_parent_for_unified_tool_id(
    tool_call_id: str,
    *,
    spawns_by_step: dict[str, TaskScope],
    tool_display_by_call_id: dict[str, Any],
) -> Any | None:
    """Return the Task delegation card for a task-level unified inner tool id."""
    step_id, type_code, _, _ = parse_unified_tool_call_id(tool_call_id)
    if not step_id or type_code != "t":
        return None
    scope = spawns_by_step.get(step_id)
    if scope is None:
        return None
    return tool_display_by_call_id.get(scope[0])


def row_key_for_subgraph_tool(
    namespace: tuple[str, ...],
    tool_call_id: str,
    *,
    task_scope: TaskScope | None = None,
) -> str:
    """Row key for a subgraph tool on a parent step/task card."""
    tid = str(tool_call_id).strip()
    _, type_code, _, _ = parse_unified_tool_call_id(tid)
    if type_code == "t":
        return tid
    return scoped_subgraph_tool_key(namespace, tid, task_scope=task_scope)


def try_bind_namespace_to_unlinked_spawn(
    bindings: dict[tuple[str, ...], TaskScope],
    spawns_by_step: dict[str, TaskScope],
    namespace: tuple[str, ...],
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
) -> bool:
    """Bind a subgraph namespace to a spawn that has no namespace yet."""
    if not namespace or namespace in bindings:
        return False
    linked_spawn_ids = {scope[0] for scope in bindings.values()}
    unlinked = [scope for scope in spawns_by_step.values() if scope[0] not in linked_spawn_ids]
    if len(unlinked) != 1:
        return False
    scope = unlinked[0]
    bindings[namespace] = scope
    if pending_unscoped_namespaces is not None:
        try:
            pending_unscoped_namespaces.remove(namespace)
        except ValueError:
            pass
    return True


def scoped_subgraph_tool_key(
    namespace: tuple[str, ...],
    tool_call_id: str,
    *,
    task_scope: TaskScope | None = None,
) -> str:
    """Build unified tool call ID for subgraph (task-level) tool rows."""
    tid = str(tool_call_id).strip()
    parsed_sid, type_code, _, _ = parse_unified_tool_call_id(tid)
    if parsed_sid and type_code == "t":
        return tid

    short_tid = _shorten_tool_call_id(tid)
    if not namespace:
        return short_tid

    step_id = task_scope_step_id(task_scope) if task_scope else ""
    task_idx = task_scope_task_idx(task_scope, step_id) if task_scope else 0

    if step_id:
        return _format_unified_tool_call_id(step_id, f"t{task_idx}", short_tid)

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


def _maybe_bind_one_pending_namespace(
    bindings: dict[tuple[str, ...], TaskScope],
    pending_unscoped_namespaces: deque[tuple[str, ...]],
    scope: TaskScope,
    spawns_by_step: dict[str, TaskScope],
) -> None:
    """Bind a deferred namespace only when there is a single unambiguous pending ns."""
    task_call_id = scope[0]
    if any(bound == scope for bound in bindings.values()):
        return
    unbound = [ns for ns in pending_unscoped_namespaces if ns not in bindings]
    if len(unbound) != 1:
        return
    linked_task_ids = {s[0] for s in bindings.values()}
    unlinked = [s for s in spawns_by_step.values() if s[0] not in linked_task_ids]
    if len(unlinked) != 1 or unlinked[0][0] != task_call_id:
        return
    ns = unbound[0]
    bindings[ns] = scope
    remaining = deque(n for n in pending_unscoped_namespaces if n != ns)
    pending_unscoped_namespaces.clear()
    pending_unscoped_namespaces.extend(remaining)


def register_task_spawn_for_step(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    spawns_by_step: dict[str, TaskScope],
    scope: TaskScope,
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
) -> None:
    """Record a task spawn for ``scope[2]`` and bind any namespaces that arrived early."""
    queue.append(scope)
    step_id = task_scope_step_id(scope)
    if not step_id:
        return
    spawns_by_step[step_id] = scope
    if pending_unscoped_namespaces is not None:
        _maybe_bind_one_pending_namespace(
            bindings, pending_unscoped_namespaces, scope, spawns_by_step
        )


def maybe_bind_namespace(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    namespace: tuple[str, ...],
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
) -> None:
    """Defer ``namespace`` until a spawn is registered, or bind via the spawn queue."""
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
    """Resolve the UI parent for subgraph tools (Task card preferred over step)."""
    if scope is None:
        return None
    task_parent = tool_display_by_call_id.get(scope[0])
    if task_parent is not None:
        return task_parent
    step_id = task_scope_step_id(scope)
    if step_id:
        return step_cards.get(step_id)
    return None


__all__ = [
    "TaskScope",
    "is_step_level_task_tool_id",
    "is_unified_tool_call_id",
    "normalize_step_task_tool_call_id",
    "normalize_unified_tool_call_id",
    "_shorten_tool_call_id",
    "enqueue_task_spawn",
    "maybe_bind_namespace",
    "parse_unified_tool_call_id",
    "register_task_spawn_for_step",
    "resolve_step_id_from_subgraph_tool",
    "resolve_task_parent_for_unified_tool_id",
    "resolve_task_parent_lookup",
    "resolve_task_scope_for_namespace",
    "row_key_for_subgraph_tool",
    "scoped_subgraph_tool_key",
    "step_level_parent_task_call_id",
    "task_scope_step_id",
    "task_scope_task_idx",
    "try_bind_namespace_to_unlinked_spawn",
]
