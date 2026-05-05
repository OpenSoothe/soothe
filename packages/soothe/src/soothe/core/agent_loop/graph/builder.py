"""Compile the Agent Loop LangGraph (RFC-620).

The graph checkpoint namespace uses ``loop_id`` via ``configurable.thread_id`` when a
checkpointer is attached. Persistence for goals remains ``AgentLoopStateManager``.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from .loop_iteration import emit_max_iterations_terminal, run_single_iteration
from .runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


def build_agent_loop_graph(ctx: LoopRuntimeContext):
    """Build and compile the Loop orchestrator graph."""

    async def iteration_body(state: dict[str, Any]) -> dict[str, Any]:
        if ctx.loop_state.iteration >= ctx.loop_state.max_iterations:
            await emit_max_iterations_terminal(ctx)
            return {"last_outcome": "max_iterations"}
        outcome = await run_single_iteration(ctx)
        return {"last_outcome": outcome}

    def route_after_iteration(state: dict[str, Any]) -> str:
        last = state.get("last_outcome")
        if last == "continue":
            return "loop"
        return END

    graph = StateGraph(dict)
    graph.add_node("iteration_body", iteration_body)
    graph.add_edge(START, "iteration_body")
    graph.add_conditional_edges(
        "iteration_body",
        route_after_iteration,
        {"loop": "iteration_body", END: END},
    )
    return graph.compile()
