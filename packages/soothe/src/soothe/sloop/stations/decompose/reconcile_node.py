"""RECONCILE station: drain proposals and commit to CE StepDAG (RFC-904)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.decompose.reconcile import (
    drain_executor_proposals,
    reconcile_proposals_deterministic,
)
from soothe.sloop.orchestrator.node_base import (
    LoopNode,
    NodeResult,
    RouteDecision,
    _maybe_await,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import RECONCILE

logger = logging.getLogger(__name__)


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
    _executor_holders = (
        ("ctx.executor", getattr(ctx, "executor", None)),
        ("strange_loop.executor", getattr(ctx.strange_loop, "executor", None)),
        ("strange_loop._last_executor", getattr(ctx.strange_loop, "_last_executor", None)),
    )
    for holder_label, holder in _executor_holders:
        if holder is None:
            continue
        drained = drain_executor_proposals(holder)
        if drained:
            logger.debug(
                "[reconcile] drained %d proposal(s) from '%s'",
                len(drained),
                holder_label,
            )
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
    if len(unique) != len(proposals):
        logger.debug("[reconcile] dedup %d → %d proposals", len(proposals), len(unique))
    logger.debug("[reconcile] collected %d proposal(s) from scratch+executor", len(unique))
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
        if not proposals:
            logger.debug(
                "[reconcile] no proposals to commit (ce=%s goal=%s cfg=%s)",
                ctx.ce is not None,
                ctx.ce_goal_id,
                cfg is not None,
            )
        if proposals and ctx.ce is not None and ctx.ce_goal_id and cfg is not None:
            result = await reconcile_proposals_deterministic(
                ctx.ce,
                ctx.ce_goal_id,
                proposals,
                config=cfg,
            )
            logger.info(
                "[reconcile] committed=%s decomposed=%s rejected=%s",
                result.committed_step_ids,
                result.decomposed_parent_ids,
                [f"{r.parent_step_id}:{r.reason}" for r in result.rejected],
            )
            if not result.committed_step_ids:
                from soothe.context.models import StepExecution

                goal = await _maybe_await(ctx.ce.get_goal(ctx.ce_goal_id))
                if goal is not None:
                    rejected_parents = {item.parent_step_id for item in result.rejected}
                    for parent_id in rejected_parents:
                        parent = goal.steps.nodes.get(parent_id)
                        if parent is not None and parent.kind == "eval":
                            reasons = [
                                item.reason
                                for item in result.rejected
                                if item.parent_step_id == parent_id
                            ]
                            execution = StepExecution(
                                outcome={
                                    "kind": "eval",
                                    "coverage": "failed"
                                    if "identical_eval_continuation" in reasons
                                    else "complete",
                                    "rejected_proposals": reasons,
                                }
                            )
                            if "identical_eval_continuation" in reasons:
                                goal.steps.mark_failed(parent_id, execution)
                            else:
                                goal.steps.mark_completed(parent_id, execution)
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
