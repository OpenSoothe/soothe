"""Task-tool namespace binding — pure helpers for subgraph stream routing.

Subgraph namespaces bind to spawns using unified tool_call_id format:
``{step_wire}:{type}:{tool}:{idx}`` where type is ``s`` for step-level or ``t{n}``
for task-level. The step_id embedded in tool_call_ids provides the correlation key
between LangGraph ``tools:…`` namespaces and main-graph ``task`` spawns.

Unified tool call ID format for step-level and task-level tool calls.
"""

from __future__ import annotations

from collections import deque
from typing import Any, NamedTuple, TypeAlias

TaskScope: TypeAlias = tuple[str, str, str]
"""``(task_tool_call_id, subagent_type, step_id)`` — ``step_id`` may be empty."""


class ParsedUnifiedToolCallId(NamedTuple):
    """Parsed components of a unified tool_call_id."""

    step_id: str
    type_code: str
    task_idx: int | None
    tool_info: str

    @classmethod
    def empty(cls, *, tool_info: str = "") -> ParsedUnifiedToolCallId:
        """Non-unified or empty id sentinel."""
        return cls("", "", None, tool_info)


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
    """Extract tool_info from colon segments after the type segment.

    Returns everything after ``parts[1]`` joined by ``":"``. The canonical wire form
    is ``{name}:{idx}`` (e.g. ``grep:0``), but providers that stamp opaque call ids
    without an ``:idx`` suffix (Kimi ``tool-{uuid}``, OpenAI ``call_{uuid}``) are
    preserved verbatim so the leading ``{step_wire}:{type}:`` marker can still
    recover the step id.
    """
    if len(parts) >= 3:
        return ":".join(parts[2:]).strip()
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


def parse_unified_tool_call_id(tool_call_id: str) -> ParsedUnifiedToolCallId:
    """Parse unified tool_call_id format into components.

    Recognition rules (in order):

    1. The id must contain at least three colon-separated segments.
    2. ``parts[0]`` must be a wire step fragment (underscore form, no hyphen — e.g.
       ``GHT_01``). This is the structural marker that distinguishes a stamped
       unified id from a raw provider id like ``functions.grep:0``.
    3. ``parts[1]`` must be ``s`` (step-level) or ``t{N}`` where ``{N}`` is an
       integer (task-level).
    4. Everything after ``parts[1]`` is the tool_info, joined by ``":"``.

    Canonical providers stamp ``{name}:{idx}`` tool_info (``GHT_01:s:grep:0``).
    Opaque-id providers may stamp something like ``GHT_01:s:tool-{uuid}`` — both
    forms recover the step_id correctly. Tool_info is returned verbatim so callers
    that need a structured ``name:idx`` form must validate it themselves.

    Args:
        tool_call_id: Unified tool_call_id string.

    Returns:
        Parsed components: step_id, type_code, task_idx, tool_info.
        Non-unified ids use empty step_id/type_code and preserve the raw id in tool_info.
    """
    tid = str(tool_call_id).strip()
    if not tid:
        return ParsedUnifiedToolCallId.empty()

    parts = tid.split(":")
    if len(parts) < 3 or not _is_wire_step_fragment(parts[0]):
        return ParsedUnifiedToolCallId.empty(tool_info=tid)

    type_part = parts[1]
    if type_part == "s":
        type_code = "s"
        task_idx: int | None = None
    elif type_part.startswith("t") and len(type_part) > 1:
        try:
            task_idx = int(type_part[1:])
        except ValueError:
            return ParsedUnifiedToolCallId.empty(tool_info=tid)
        type_code = "t"
    else:
        return ParsedUnifiedToolCallId.empty(tool_info=tid)

    tool_info = _tool_info_from_unified_parts(parts)
    if not tool_info:
        return ParsedUnifiedToolCallId.empty(tool_info=tid)

    step_id = _step_id_from_unified_fragment(parts[0])
    return ParsedUnifiedToolCallId(step_id, type_code, task_idx, tool_info)


def is_step_level_task_tool_id(tool_call_id: str) -> bool:
    """True for unified main-graph ``task`` delegation ids (``{step}:s:task:…``)."""
    _, type_code, _, tool_info = parse_unified_tool_call_id(tool_call_id)
    if type_code != "s":
        return False
    return (tool_info or "").split(":")[0] == "task"


def is_inner_subgraph_task_tool_id(tool_call_id: str) -> bool:
    """True for inner explore ``task`` rows (``{step}:t{n}:task:…``), not main spawns."""
    _, type_code, _, tool_info = parse_unified_tool_call_id(tool_call_id)
    if type_code != "t":
        return False
    return (tool_info or "").split(":")[0] == "task"


def _task_index_from_task_tool_call_id(tool_call_id: str) -> int | None:
    """Extract delegation index from a main-graph ``task`` tool_call_id, if present."""
    tid = str(tool_call_id).strip()
    if not tid or is_inner_subgraph_task_tool_id(tid):
        return None
    parsed_sid, type_code, task_idx, tool_info = parse_unified_tool_call_id(tid)
    if type_code == "s":
        head = (tool_info or "").split(":")[0]
        if head != "task":
            return None
        tail = (tool_info or "").split(":")[-1]
        return int(tail) if tail.isdigit() else 0
    if type_code == "t":
        head = (tool_info or "").split(":")[0]
        if head == "task":
            tail = (tool_info or "").split(":")[-1]
            if tail.isdigit():
                return int(tail)
        if task_idx is not None:
            return task_idx
    short = _shorten_tool_call_id(tid)
    if short.startswith("task"):
        tail = short.split(":")[-1]
        return int(tail) if tail.isdigit() else 0
    _ = parsed_sid
    return None


def normalize_main_task_delegation_id(
    step_id: str,
    tool_call_id: str,
    *,
    tool_name: str = "",
) -> str:
    """Normalize a main-graph ``task`` delegation to ``{step_wire}:s:task:{n}``.

    Providers sometimes stamp step-level delegations with task-level ``t{n}:…`` prefixes
    (opaque call ids). Remap those onto canonical step-level ids so spawn registration
    and subgraph ``t{n}:…`` inner tools stay aligned.
    """
    sid = str(step_id).strip()
    tcid = str(tool_call_id).strip()
    if not sid or not tcid:
        return tcid
    if is_inner_subgraph_task_tool_id(tcid):
        return tcid
    name = str(tool_name or "").strip()
    idx = _task_index_from_task_tool_call_id(tcid)
    is_task = name == "task"
    if not is_task:
        _, type_code, _, tool_info = parse_unified_tool_call_id(tcid)
        is_task = type_code in ("s", "t") and (
            (tool_info or "").split(":")[0] == "task"
            or _shorten_tool_call_id(tcid).startswith("task")
        )
    if is_task and idx is not None:
        return _format_unified_tool_call_id(sid, "s", f"task:{idx}")
    return normalize_step_task_tool_call_id(sid, tcid)


def normalize_step_task_tool_call_id(step_id: str, tool_call_id: str) -> str:
    """Return step-scoped unified id for a main-graph ``task`` delegation.

    Args:
        step_id: Execute step id.
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
        # Another step's delegation id must not be remapped onto this card.
        return tcid
    short = _shorten_tool_call_id(tcid)
    if not short.startswith("task"):
        short = "task:0"
    return _format_unified_tool_call_id(sid, "s", short)


def step_level_parent_task_call_id(step_id: str, task_idx: int | None = None) -> str:
    """Parent ``task`` row id for inner tools under ``{step_wire}:t{idx}:…``."""
    idx = 0 if task_idx is None else int(task_idx)
    return _format_unified_tool_call_id(step_id, "s", f"task:{idx}")


def task_scope_step_id(scope: TaskScope | None) -> str:
    """Return the step id from a task scope tuple, if present."""
    if not scope:
        return ""
    return str(scope[2] or "").strip()


def task_scope_task_idx(scope: TaskScope | None, step_id: str) -> int:
    """Derive task index within a step from TaskScope's task_tool_call_id.

    Parses the task index from ``scope[0]`` (e.g., ``ABC_01:s:task:0`` → 0).
    Returns 0 if the scope is empty or the task index cannot be parsed.
    """
    if not scope:
        return 0
    task_tool_call_id = str(scope[0] or "").strip()
    if not task_tool_call_id:
        return 0
    _, type_code, _, tool_info = parse_unified_tool_call_id(task_tool_call_id)
    if type_code != "s":
        return 0
    head = (tool_info or "").split(":")[0]
    if head != "task":
        return 0
    tail = (tool_info or "").split(":")[-1]
    if tail.isdigit():
        return int(tail)
    return 0


def row_key_for_subgraph_tool(
    namespace: tuple[str, ...],
    tool_call_id: str,
    *,
    task_scope: TaskScope | None = None,
) -> str:
    """Row key for a subgraph tool on a parent step/task card."""
    tid = str(tool_call_id).strip()
    parsed_sid, type_code, parsed_idx, tool_info = parse_unified_tool_call_id(tid)
    # Re-map task-level IDs to the bound task_scope's step_id
    if type_code == "t" and task_scope is not None:
        bound_step_id = task_scope_step_id(task_scope)
        bound_task_idx = task_scope_task_idx(task_scope, bound_step_id)
        if bound_step_id and (parsed_sid != bound_step_id or parsed_idx != bound_task_idx):
            # Server sent wrong step_id/task_idx - remap to correct ones from binding
            return _format_unified_tool_call_id(bound_step_id, f"t{bound_task_idx}", tool_info)
    if type_code == "t":
        return tid
    return scoped_subgraph_tool_key(namespace, tid, task_scope=task_scope)


def resolve_task_scope_for_subgraph_tool(
    tool_call_id: str,
    spawns_by_step: dict[str, TaskScope],
    spawns_by_task_id: dict[str, TaskScope] | None = None,
) -> TaskScope | None:
    """Resolve the task spawn for a subgraph tool using unified id components."""
    tcid = str(tool_call_id).strip()
    if not tcid:
        return None
    step_id, type_code, task_idx, _ = parse_unified_tool_call_id(tcid)
    if type_code == "t" and step_id and task_idx is not None:
        if spawns_by_task_id:
            parent_id = step_level_parent_task_call_id(step_id, task_idx)
            scope = spawns_by_task_id.get(parent_id)
            if scope is not None:
                return scope
            for scope in spawns_by_task_id.values():
                sid = task_scope_step_id(scope)
                if sid == step_id and task_scope_task_idx(scope, sid) == task_idx:
                    return scope
            if any(task_scope_step_id(s) == step_id for s in spawns_by_task_id.values()):
                return None
        if task_idx == 0:
            return spawns_by_step.get(step_id)
        return None
    if step_id:
        return spawns_by_step.get(step_id)
    return None


def try_bind_namespace_from_tool_call_id(
    bindings: dict[tuple[str, ...], TaskScope],
    spawns_by_step: dict[str, TaskScope],
    namespace: tuple[str, ...],
    tool_call_id: str,
    *,
    spawns_by_task_id: dict[str, TaskScope] | None = None,
) -> bool:
    """Bind ``namespace`` using the execute step id embedded in a unified tool_call_id.

    Parallel waves stamp subgraph tools as ``{step_wire}:t{idx}:…``; the step id is the
    correlation key between a LangGraph ``tools:…`` namespace and the main-graph ``task`` spawn.
    """
    tcid = str(tool_call_id).strip()
    if not namespace or not tcid or is_inner_subgraph_task_tool_id(tcid):
        return False
    scope = resolve_task_scope_for_subgraph_tool(
        tcid,
        spawns_by_step,
        spawns_by_task_id,
    )
    if scope is None:
        return False
    step_id = task_scope_step_id(scope)
    if not step_id:
        return False
    if namespace in bindings:
        if task_scope_step_id(bindings[namespace]) == step_id:
            return False
        _, type_code, _, tool_info = parse_unified_tool_call_id(tcid)
        if type_code == "t" and (tool_info or "").split(":")[0] != "task":
            bindings[namespace] = scope
            return True
        return False
    bindings[namespace] = scope
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


def register_task_spawn_for_step(
    bindings: dict[tuple[str, ...], TaskScope],
    queue: deque[TaskScope],
    spawns_by_step: dict[str, TaskScope],
    scope: TaskScope,
    *,
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None = None,
    spawns_by_task_id: dict[str, TaskScope] | None = None,
) -> None:
    """Record a task spawn for ``scope[2]``.

    Namespace binding is deferred to unified ID-based matching via
    :func:`try_bind_namespace_from_tool_call_id`.
    """
    queue.append(scope)
    step_id = task_scope_step_id(scope)
    task_call_id = str(scope[0] or "").strip()
    if not step_id:
        return
    if spawns_by_task_id is not None and task_call_id:
        spawns_by_task_id[task_call_id] = scope
    existing = spawns_by_step.get(step_id)
    if existing is not None and is_step_level_task_tool_id(str(existing[0])):
        if is_inner_subgraph_task_tool_id(task_call_id):
            return
        if (
            is_step_level_task_tool_id(task_call_id)
            and normalize_step_task_tool_call_id(step_id, task_call_id) != str(existing[0]).strip()
        ):
            return
    spawns_by_step[step_id] = scope


def prune_bound_pending_namespaces(
    bindings: dict[tuple[str, ...], TaskScope],
    pending_unscoped_namespaces: deque[tuple[str, ...]] | None,
) -> None:
    """Drop namespaces from the pending deque once they are bound."""
    if pending_unscoped_namespaces is None or not bindings:
        return
    filtered = [ns for ns in pending_unscoped_namespaces if ns not in bindings]
    pending_unscoped_namespaces.clear()
    pending_unscoped_namespaces.extend(filtered)


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
    "is_inner_subgraph_task_tool_id",
    "is_step_level_task_tool_id",
    "is_unified_tool_call_id",
    "normalize_main_task_delegation_id",
    "normalize_step_task_tool_call_id",
    "normalize_unified_tool_call_id",
    "_shorten_tool_call_id",
    "prune_bound_pending_namespaces",
    "parse_unified_tool_call_id",
    "ParsedUnifiedToolCallId",
    "register_task_spawn_for_step",
    "resolve_task_parent_lookup",
    "resolve_task_scope_for_subgraph_tool",
    "resolve_task_scope_for_namespace",
    "row_key_for_subgraph_tool",
    "scoped_subgraph_tool_key",
    "step_level_parent_task_call_id",
    "task_scope_step_id",
    "task_scope_task_idx",
    "try_bind_namespace_from_tool_call_id",
]
