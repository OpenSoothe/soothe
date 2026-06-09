"""Resolve CoreAgent checkpointer for loop graph nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.loop.engine.agent_loop import AgentLoop


def core_agent_checkpointer(agent_loop: AgentLoop) -> Any | None:
    """Return the LangGraph checkpointer wired on CoreAgent, if any."""
    graph = getattr(agent_loop.core_agent, "graph", None)
    if graph is None:
        return None
    return getattr(graph, "checkpointer", None)
