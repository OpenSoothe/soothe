"""Iteration cap check before per-iteration work (RFC-220 ``iteration_gate``).

Migrated to ``LoopNode`` (RFC-903 P2): the node is a ``CheckLimitsNode``
subclass. Terminal branches (max_iterations, rate_limited) emit their own
completion events in ``process`` and return ``RouteDecision(kind="terminal")``.
The legacy ``node_iteration_gate`` function is retained as a thin wrapper.

RFC-903 P3: ``begin_iteration`` is folded into this node's ``process()``
non-terminal branch — scratch reset, start anchor capture, and
``iteration_started`` emission happen here, eliminating the separate
``BEGIN_ITERATION`` station and the unconditional edge to ``GATHER_EVIDENCE``.
The legacy ``node_iteration_start`` function is retained for backward
compatibility with tests/imports.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.sloop.orchestrator.checkpointer import core_agent_checkpointer
from soothe.sloop.orchestrator.node_base import LoopNode, NodeResult, RouteDecision
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.execute.max_iterations_terminal import emit_max_iterations_terminal

logger = logging.getLogger(__name__)

_DEFAULT_RATE_LIMIT_THRESHOLD = 3


def _get_rate_limit_threshold(ctx: LoopRuntimeContext) -> int:
    """Resolve the consecutive rate limit error threshold.

    Checks ``agent.loop.thread_switch_policy.consecutive_rate_limit_threshold``
    from config if available, otherwise falls back to the default (3).
    """
    try:
        loop_cfg = ctx.strange_loop.config.agent.loop
        tsp = getattr(loop_cfg, "thread_switch_policy", None)
        if tsp is not None and getattr(tsp, "consecutive_rate_limit_threshold", None) is not None:
            return tsp.consecutive_rate_limit_threshold
    except (AttributeError, TypeError):
        pass
    return _DEFAULT_RATE_LIMIT_THRESHOLD


class CheckLimitsNode(LoopNode):
    """Stop with terminal completion when the iteration budget is exhausted.

    Non-LLM node (``call_kind is None``). Terminal branches emit completion
    events in ``process`` and return ``RouteDecision(kind="terminal")`` so
    the router routes to END.
    """

    station = "check_limits"
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        # Resumable interrupt edge case: when a goal was just resumed in place
        # from an ``interrupted``/``cancelled`` cursor (recovery_valid_resume)
        # and the persisted iteration happens to sit exactly at the budget
        # boundary, the gate must not emit max_iterations before the resumed
        # run does any work. Grant one grace iteration so the resumed goal can
        # make progress before the budget check applies again. Without this, a
        # cancel-then-retry at the final iteration would immediately
        # terminalize the goal.
        _resumed = bool(getattr(ctx, "recovery_valid_resume", False))
        if not _resumed and ctx.loop_state.iteration >= ctx.loop_state.max_iterations:
            await emit_max_iterations_terminal(ctx)
            return NodeResult(payload="max_iterations")

        # Rate limit circuit breaker: stop when consecutive 429s exceed threshold
        metrics = ctx.checkpoint.thread_health_metrics
        try:
            rate_limit_errors = int(getattr(metrics, "consecutive_rate_limit_errors", 0))
        except (TypeError, ValueError):
            rate_limit_errors = 0
        threshold = _get_rate_limit_threshold(ctx)
        if rate_limit_errors >= threshold:
            logger.warning(
                "[Rate limit] Loop stopping: %d consecutive rate limit errors >= threshold %d",
                rate_limit_errors,
                threshold,
            )
            await emit_rate_limit_terminal(ctx)
            return NodeResult(payload="rate_limited")

        # RFC-903 P3: folded begin_iteration into the non-terminal branch.
        # Scratch reset, start anchor capture, and iteration_started emission
        # previously lived in a separate BEGIN_ITERATION node.
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

        return NodeResult(payload="continue", events=events)

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        if result.payload in ("max_iterations", "rate_limited"):
            return RouteDecision(
                kind="terminal",
                state_patch={"last_outcome": result.payload},
            )
        # RFC-226 fix: clear resume_synth to prevent stale flag from prior
        # clarification synthesis from affecting subsequent goals/iterations.
        # Previously cleared by the folded begin_iteration node.
        return RouteDecision(
            kind="proceed",
            state_patch={
                "plan_route": None,
                "assess_route": None,
                "last_outcome": None,
                "resume_synth": None,
            },
        )


# Singleton instance for the graph builder.
node: CheckLimitsNode = CheckLimitsNode()


async def node_iteration_gate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Legacy entry point — delegates to :class:`CheckLimitsNode`."""
    return await node(ctx, _state)


async def emit_rate_limit_terminal(ctx: LoopRuntimeContext) -> None:
    """Emit failure completion after consecutive rate limit errors."""
    from datetime import UTC, datetime

    from soothe.sloop.engine.goal_interrupt_record import (
        append_goal_interrupted_ledger_pair,
    )
    from soothe.sloop.state.schemas import PlanResult
    from soothe.sloop.utils.reflection import _default_agent_decision

    state = ctx.loop_state
    goal_record = ctx.goal_record
    state_manager = ctx.state_manager
    checkpoint = ctx.checkpoint

    # RFC-214: mark the goal's partial work before the terminal status is set
    # so the next goal's planning projection can bound this segment.
    await append_goal_interrupted_ledger_pair(
        ctx,
        reason="rate_limited",
        detail=f"{int(getattr(checkpoint.thread_health_metrics, 'consecutive_rate_limit_errors', 0) or 0)} consecutive rate-limit errors",
    )

    if goal_record is not None:
        goal_record.status = "failed"
        goal_record.completed_at = datetime.now(UTC)
    checkpoint.status = "idle"
    checkpoint.thread_health_metrics.last_goal_status = "failed"
    await state_manager.save(checkpoint)

    result = state.previous_plan or PlanResult(
        status="replan",
        plan_action="new",
        decision=_default_agent_decision(state.goal),
        evidence_summary=state.evidence_summary,
        goal_progress="none",
        next_action="Rate limit reached; pausing to avoid wasting quota.",
    )
    await ctx.emit(
        "completed",
        {
            "result": result,
            "step_results_count": len(state.step_results),
        },
    )
