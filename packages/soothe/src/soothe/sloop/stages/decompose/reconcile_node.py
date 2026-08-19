"""RECONCILE station: drain proposals and commit to CE StepDAG (RFC-904)."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from soothe.sloop.decompose.reconcile import (
    drain_executor_proposals,
    reconcile_proposals_deterministic,
)
from soothe.sloop.orchestrator.node_base import LoopNode, NodeResult, RouteDecision
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import RECONCILE

logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _collect_proposals(ctx: LoopRuntimeContext) -> list[Any]:
    """Drain proposals from scratch and any executor-like sinks."""
    proposals: list[Any] = []
    if ctx.scratch.decompose_proposals:
        proposals.extend(list(ctx.scratch.decompose_proposals))
        ctx.scratch.decompose_proposals.clear()

    for holder_name in ("decompose_proposals",):
        queued = getattr(ctx, holder_name, None)
        if isinstance(queued, list) and queued is not ctx.scratch.decompose_proposals:
            proposals.extend(list(queued))
            queued.clear()

    # Executor instances attach to strange_loop during tests / optional wiring.
    for holder in (
        getattr(ctx, "executor", None),
        getattr(ctx.strange_loop, "executor", None),
        getattr(ctx.strange_loop, "_last_executor", None),
    ):
        if holder is None:
            continue
        drained = drain_executor_proposals(holder)
        if drained:
            proposals.extend(drained)

    if not proposals:
        return []

    seen: set[tuple[str, int, str]] = set()
    unique: list[Any] = []
    for p in proposals:
        key = (
            p.parent_step_id,
            getattr(p, "wave_seq", 0),
            "|".join(s.description for s in p.subtasks),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


class ReconcileNode(LoopNode):
    """Commit queued DecompositionProposals; route to DISPATCH or ROOT_EVAL."""

    station = RECONCILE
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        proposals = _collect_proposals(ctx)
        cfg = getattr(ctx.strange_loop.config.agent.loop, "decompose", None)
        if proposals and ctx.ce is not None and ctx.ce_goal_id and cfg is not None:
            result = await reconcile_proposals_deterministic(
                ctx.ce,
                ctx.ce_goal_id,
                proposals,
                config=cfg,
            )
            logger.info(
                "[reconcile] committed=%s decomposed=%s rejected=%d",
                result.committed_step_ids,
                result.decomposed_parent_ids,
                len(result.rejected),
            )
            try:
                ctx.ce.defer_save()
            except Exception:
                logger.debug("[reconcile] CE defer_save failed", exc_info=True)
        elif proposals:
            logger.warning(
                "[reconcile] dropped %d proposal(s) (ce=%s goal=%s)",
                len(proposals),
                ctx.ce is not None,
                ctx.ce_goal_id,
            )

        route = "root_eval"
        if ctx.ce is not None and ctx.ce_goal_id:
            goal = await _maybe_await(ctx.ce.get_goal(ctx.ce_goal_id))
            if goal is not None:
                if goal.steps.ready_steps():
                    route = "dispatch"
                else:
                    route = "root_eval"

        return NodeResult(payload={"reconcile_route": route})

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        payload = result.payload if isinstance(result.payload, dict) else {}
        return RouteDecision(
            kind="proceed",
            state_patch={"reconcile_route": str(payload.get("reconcile_route") or "root_eval")},
        )


node = ReconcileNode()
