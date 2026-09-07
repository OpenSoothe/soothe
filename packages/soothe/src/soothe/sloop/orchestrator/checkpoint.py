"""LangGraph checkpoint helpers and thread-id grammar for StrangeLoop."""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from soothe.sloop.strange_loop import StrangeLoop

_STRANGE_LOOP_THREAD_SUFFIX: Final = "__strange_loop"
_INTAKE_THREAD_MARKER: Final = "__intake__"
_SYNTHESIS_THREAD_MARKER: Final = "__synth_gc__"
_THREAD_TOKEN_SEP: Final = "__"

ThreadKind = Literal["loop", "intake", "execute_step", "synthesis"]


def strange_loop_thread_id(loop_id: str) -> str:
    """Checkpoint `thread_id` for the StrangeLoop graph (isolated from CoreAgent)."""
    return f"{loop_id}{_STRANGE_LOOP_THREAD_SUFFIX}"


def intake_thread_id(loop_id: str, wire: str) -> str:
    """Checkpoint `thread_id` for an intake-only subagent delegation.

    Args:
        loop_id: Owning loop identifier.
        wire: Wire / subagent name; blank falls back to `specialist`.

    Returns:
        `{loop_id}__intake__{wire}`.
    """
    safe_wire = (wire or "specialist").strip() or "specialist"
    return f"{loop_id}{_INTAKE_THREAD_MARKER}{safe_wire}"


def execute_step_thread_id(main_thread_id: str) -> str:
    """Fresh random `thread_id` for an execute step, decoupled from the step id.

    Args:
        main_thread_id: Loop main thread id to prefix.

    Returns:
        `{main_thread_id}__{hex5}` with 5 random hex chars.
    """
    return f"{main_thread_id}{_THREAD_TOKEN_SEP}{secrets.token_hex(3)[:5]}"


def synthesis_thread_id(parent_thread_id: str) -> str:
    """Ephemeral `thread_id` for goal-completion synthesis.

    A dedicated id keeps the checkpointer from loading the parent thread's full
    conversation into the synthesis model call.

    Args:
        parent_thread_id: StrangeLoop / user thread identifier.

    Returns:
        `{parent_thread_id}__synth_gc__{uuid}` (stable prefix for log grep).
    """
    return f"{parent_thread_id}{_SYNTHESIS_THREAD_MARKER}{uuid.uuid4().hex}"


def thread_kind(thread_id: str) -> ThreadKind:
    """Classify a thread id by its `__` markers and suffixes.

    Synthesis and intake markers are checked first because either may be appended
    to any parent thread. A bare id with no `__` token is the loop main thread
    (main thread id == loop_id).

    Examples:
        >>> thread_kind("loop-1__strange_loop")
        'loop'
        >>> thread_kind("loop-1__intake__planner")
        'intake'
        >>> thread_kind("loop-1__a3f7c")
        'execute_step'
        >>> thread_kind("loop-1__a3f7c__synth_gc__0badc0de")
        'synthesis'
        >>> thread_kind("loop-1")
        'loop'

    Args:
        thread_id: Checkpoint thread id built by one of this module's constructors.

    Returns:
        The thread kind.
    """
    tid = thread_id or ""
    if _SYNTHESIS_THREAD_MARKER in tid:
        return "synthesis"
    if _INTAKE_THREAD_MARKER in tid:
        return "intake"
    if tid.endswith(_STRANGE_LOOP_THREAD_SUFFIX):
        return "loop"
    if _THREAD_TOKEN_SEP in tid:
        return "execute_step"
    return "loop"


def strange_loop_configurable(loop_id: str, **extra: Any) -> dict[str, Any]:
    """Runnable `configurable` for StrangeLoop graph `ainvoke` / `aget_state`."""
    conf: dict[str, Any] = {
        "thread_id": strange_loop_thread_id(loop_id),
    }
    conf.update(extra)
    return conf


def intake_only_invoke_config(
    loop_id: str,
    wire: str,
    *,
    workspace: str | None = None,
) -> dict[str, Any]:
    """RunnableConfig for intake-only CompiledSubAgent invokes from `delegate`.

    Uses a dedicated thread so nested graphs that inherit the parent checkpointer
    cannot write into the StrangeLoop interrupt lineage.
    """
    conf: dict[str, Any] = {
        "thread_id": intake_thread_id(loop_id, wire),
    }
    if workspace and str(workspace).strip():
        conf["workspace"] = str(workspace).strip()
    return {"configurable": conf}


def core_agent_checkpointer(strange_loop: StrangeLoop) -> Any | None:
    """Return the LangGraph checkpointer wired on CoreAgent, if any.

    Does not force LazyCoreAgent materialization. Callers must materialize
    (and attach the async checkpointer) before compiling the loop graph.
    """
    agent = strange_loop.core_agent
    if getattr(agent, "is_materialized", True) is False:
        return None
    try:
        graph = getattr(agent, "graph", None)
        if graph is None:
            return None
        return getattr(graph, "checkpointer", None)
    except NotImplementedError:
        return None
