"""Resolve CoreAgent checkpointer for loop graph nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.sloop.engine.strange_loop import StrangeLoop


def core_agent_checkpointer(strange_loop: StrangeLoop) -> Any | None:
    """Return the LangGraph checkpointer wired on CoreAgent, if any."""
    try:
        graph = getattr(strange_loop.core_agent, "graph", None)
        if graph is None:
            return None
        return getattr(graph, "checkpointer", None)
    except NotImplementedError:
        # ClaudeCoreAgent doesn't use LangGraph
        return None
