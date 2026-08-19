"""Loop budget / rate-limit gate helpers (re-homed from legacy check_limits).

DISPATCH calls :func:`enforce_loop_budget` before claiming work so the RFC-904
graph retains the iteration and consecutive-429 stops without a separate
``check_limits`` station.
"""

from __future__ import annotations

import logging
from typing import Literal

from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.execute.max_iterations_terminal import emit_max_iterations_terminal

logger = logging.getLogger(__name__)

_DEFAULT_RATE_LIMIT_THRESHOLD = 3

BudgetTerminal = Literal["max_iterations", "rate_limited"]


def _get_rate_limit_threshold(ctx: LoopRuntimeContext) -> int:
    """Resolve consecutive rate-limit threshold from loop config."""
    try:
        loop_cfg = ctx.strange_loop.config.agent.loop
        tsp = getattr(loop_cfg, "thread_switch_policy", None)
        if tsp is not None and getattr(tsp, "consecutive_rate_limit_threshold", None) is not None:
            return tsp.consecutive_rate_limit_threshold
    except (AttributeError, TypeError):
        pass
    return _DEFAULT_RATE_LIMIT_THRESHOLD


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

    await append_goal_interrupted_ledger_pair(
        ctx,
        reason="rate_limited",
        detail=(
            f"{int(getattr(checkpoint.thread_health_metrics, 'consecutive_rate_limit_errors', 0) or 0)} "
            "consecutive rate-limit errors"
        ),
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


async def enforce_loop_budget(ctx: LoopRuntimeContext) -> BudgetTerminal | None:
    """Return a terminal outcome when iteration or rate-limit budget is exhausted.

    Resumed goals (``recovery_valid_resume``) get one grace iteration at the
    budget boundary so cancel-then-retry at the final iteration can progress.
    """
    resumed = bool(getattr(ctx, "recovery_valid_resume", False))
    iteration = int(getattr(ctx.loop_state, "iteration", 0) or 0)
    max_iterations = int(getattr(ctx.loop_state, "max_iterations", 0) or 0)
    if max_iterations > 0 and not resumed and iteration >= max_iterations:
        await emit_max_iterations_terminal(ctx)
        return "max_iterations"

    metrics = getattr(ctx.checkpoint, "thread_health_metrics", None)
    try:
        rate_limit_errors = int(getattr(metrics, "consecutive_rate_limit_errors", 0) or 0)
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
        return "rate_limited"
    return None


__all__ = [
    "BudgetTerminal",
    "emit_rate_limit_terminal",
    "enforce_loop_budget",
]
