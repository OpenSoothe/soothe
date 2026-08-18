"""LangGraph checkpoint helpers for StrangeLoop vs CoreAgent isolation.

CoreAgent execute streams default to ``thread_id=loop_id`` with ``checkpoint_ns=""``.
StrangeLoop parks ``await_user`` interrupts on the same checkpointer; without a
dedicated thread, deepagents / intake-only writes can advance the checkpoint head
past ``__interrupt__`` so ``Command(resume=...)`` becomes a no-op while
``pending_clarification`` still looks set.

Do **not** use a custom ``checkpoint_ns`` string for isolation: LangGraph treats
non-empty ``checkpoint_ns`` as a subgraph path and ``aget_state`` raises
``Subgraph {ns} not found``. Isolation is via dedicated ``thread_id`` values
with empty ``checkpoint_ns``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from soothe.sloop.engine.strange_loop import StrangeLoop

# Scoped under the loop UUID so CoreAgent (thread_id=loop_id) cannot orphan
# review interrupts on the shared checkpointer.
STRANGE_LOOP_THREAD_SUFFIX: Final = "__strange_loop"


def strange_loop_thread_id(loop_id: str) -> str:
    """Checkpoint ``thread_id`` for the StrangeLoop graph (isolated from CoreAgent)."""
    return f"{loop_id}{STRANGE_LOOP_THREAD_SUFFIX}"


def strange_loop_configurable(loop_id: str, **extra: Any) -> dict[str, Any]:
    """Runnable ``configurable`` for StrangeLoop graph ``ainvoke`` / ``aget_state``."""
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
    """RunnableConfig for intake-only CompiledSubAgent invokes from ``delegate``.

    Uses a dedicated thread so nested graphs that inherit the parent checkpointer
    cannot write into the StrangeLoop interrupt lineage. Leaves ``checkpoint_ns``
    unset (empty) — custom ns values are subgraph paths, not isolation keys.
    """
    safe_wire = (wire or "specialist").strip() or "specialist"
    conf: dict[str, Any] = {
        "thread_id": f"{loop_id}__intake__{safe_wire}",
    }
    if workspace and str(workspace).strip():
        conf["workspace"] = str(workspace).strip()
    return {"configurable": conf}


def snapshot_has_resumable_interrupt(snapshot: Any) -> bool:
    """True when ``aget_state`` still has a LangGraph interrupt to ``Command(resume)``."""
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if interrupts:
        return True
    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        task_interrupts = getattr(task, "interrupts", None) or ()
        if task_interrupts:
            return True
    return False


def snapshot_has_unanswered_pending(snapshot: Any) -> bool:
    """True when graph values still have a pending clarification with no answer."""
    values = getattr(snapshot, "values", {}) or {}
    return bool(values.get("pending_clarification")) and not values.get(
        "pending_clarification_answer"
    )


def core_agent_checkpointer(strange_loop: StrangeLoop) -> Any | None:
    """Return the LangGraph checkpointer wired on CoreAgent, if any.

    Does not force LazyCoreAgent materialization. Callers must materialize
    (and attach the async checkpointer) before compiling the loop graph;
    sync ``.graph`` access would compile without the async saver.
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
        # CoreAgent without LangGraph graph
        return None
