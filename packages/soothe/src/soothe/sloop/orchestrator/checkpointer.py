"""Resolve CoreAgent checkpointer for loop graph nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.sloop.engine.strange_loop import StrangeLoop


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
