"""ROOT_EVAL station: tree-green coverage gate (RFC-904; P3 assess stub)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.orchestrator.node_base import (
    LoopNode,
    NodeResult,
    RouteDecision,
    _maybe_await,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import ROOT_EVAL

logger = logging.getLogger(__name__)


class RootEvalNode(LoopNode):
    """Assess-only when StepDAG is tree-green; P3 routes to FINALIZE.

    Gap re-dispatch (new root + GapResult) lands in P4.
    """

    station = ROOT_EVAL
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        failed = False
        if ctx.ce is not None and ctx.ce_goal_id:
            goal = await _maybe_await(ctx.ce.get_goal(ctx.ce_goal_id))
            if goal is not None:
                if any(n.status == "failed" for n in goal.steps.nodes.values()):
                    failed = True
                    logger.warning("[root_eval] unresolved failed steps present")
                elif not goal.steps.tree_green():
                    # Still have pending/active — send back to dispatch if possible.
                    if goal.steps.ready_steps():
                        return NodeResult(payload={"root_eval_route": "dispatch"})
                    logger.warning("[root_eval] not tree-green and no ready; finalize anyway")

        if failed:
            # P4 B-lazy; P3 still finalize so the loop terminates with report.
            return NodeResult(payload={"root_eval_route": "finalize"})

        logger.info("[root_eval] tree-green (or no CE); finalize")
        return NodeResult(payload={"root_eval_route": "finalize"})

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        payload = result.payload if isinstance(result.payload, dict) else {}
        return RouteDecision(
            kind="proceed",
            state_patch={"root_eval_route": str(payload.get("root_eval_route") or "finalize")},
        )


node = RootEvalNode()
