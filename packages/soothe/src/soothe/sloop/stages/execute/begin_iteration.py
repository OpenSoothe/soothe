"""Iteration begin hooks and RFC-218 start anchors (RFC-220 ``iteration_start``).

Migrated to ``LoopNode`` (RFC-903 P2): the node is a ``BeginIterationNode``
subclass with the five-method lifecycle. The legacy ``node_iteration_start``
function is retained as a thin wrapper for backward compatibility.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.sloop.orchestrator.checkpointer import core_agent_checkpointer
from soothe.sloop.orchestrator.node_base import LoopNode, NodeResult, RouteDecision
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


class BeginIterationNode(LoopNode):
    """Emit iteration start, capture start anchor, reset per-iteration scratch.

    Non-LLM node (``call_kind is None``): no projection or prompt assembly.
    The ``post`` clears stale route keys (RFC-226: ``resume_synth`` must not
    survive across iterations).
    """

    station = "begin_iteration"
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        strange_loop = ctx.strange_loop
        loop_state = ctx.loop_state

        ctx.scratch = LoopPhaseScratch(iteration_perf_start=time.perf_counter())

        events: list[tuple[str, dict[str, Any]]] = [
            (
                "iteration_started",
                {
                    "iteration": loop_state.iteration,
                    "max_iterations": loop_state.max_iterations,
                },
            )
        ]

        await ctx.anchor_manager.capture_iteration_start_anchor(
            iteration=loop_state.iteration,
            thread_id=loop_state.thread_id,
            checkpointer=core_agent_checkpointer(strange_loop),
        )

        return NodeResult(payload=loop_state.iteration, events=events)

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        # RFC-226 fix: clear resume_synth to prevent stale flag from prior
        # clarification synthesis from affecting subsequent goals/iterations.
        # Without this, once set, every execution would skip record_iteration
        # and loop indefinitely.
        return RouteDecision(
            kind="proceed",
            state_patch={
                "plan_route": None,
                "assess_route": None,
                "last_outcome": None,
                "resume_synth": None,
            },
        )


# Singleton instance for the graph builder (wrap_node detects LoopNode).
node: BeginIterationNode = BeginIterationNode()


async def node_iteration_start(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Legacy entry point — delegates to :class:`BeginIterationNode`.

    Retained for backward compatibility with tests/imports that call the
    function directly. The graph builder uses the ``node`` singleton via
    ``wrap_node``.
    """
    return await node(ctx, _state)
