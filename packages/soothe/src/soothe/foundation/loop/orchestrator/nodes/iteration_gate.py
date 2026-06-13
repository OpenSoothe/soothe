"""Iteration cap check before per-iteration work (RFC-220 ``iteration_gate``)."""

from __future__ import annotations

import logging
from typing import Any

from ..runtime_context import LoopRuntimeContext
from .max_iterations_terminal import emit_max_iterations_terminal

logger = logging.getLogger(__name__)

_DEFAULT_RATE_LIMIT_THRESHOLD = 3


def _get_rate_limit_threshold(ctx: LoopRuntimeContext) -> int:
    """Resolve the consecutive rate limit error threshold.

    Checks ``ThreadSwitchPolicy.consecutive_rate_limit_threshold`` from config
    if available, otherwise falls back to the default (3).
    """
    try:
        loop_limits = ctx.strange_loop.config.agent.loop.limits
        tsp = getattr(loop_limits, "thread_switch_policy", None)
        if tsp is not None and tsp.consecutive_rate_limit_threshold is not None:
            return tsp.consecutive_rate_limit_threshold
    except (AttributeError, TypeError):
        pass
    return _DEFAULT_RATE_LIMIT_THRESHOLD


async def node_iteration_gate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Stop with terminal completion when the iteration budget is exhausted."""
    if ctx.loop_state.iteration >= ctx.loop_state.max_iterations:
        await emit_max_iterations_terminal(ctx)
        return {"last_outcome": "max_iterations"}

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
        return {"last_outcome": "rate_limited"}

    return {}


async def emit_rate_limit_terminal(ctx: LoopRuntimeContext) -> None:
    """Emit failure completion after consecutive rate limit errors."""
    from datetime import UTC, datetime

    from soothe.foundation.loop.state.schemas import PlanResult
    from soothe.foundation.loop.utils.reflection import _default_agent_decision

    state = ctx.loop_state
    goal_record = ctx.goal_record
    state_manager = ctx.state_manager
    checkpoint = ctx.checkpoint

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
