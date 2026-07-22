"""Terminal handling when ``max_iterations`` is exhausted (RFC-220 ``iteration_gate`` branch)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from soothe.sloop.state.schemas import PlanResult
from soothe.sloop.utils.reflection import _default_agent_decision

from ..orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def emit_max_iterations_terminal(ctx: LoopRuntimeContext) -> None:
    """Emit failure completion after exhausting iterations."""
    state = ctx.loop_state
    goal_record = ctx.goal_record
    state_manager = ctx.state_manager
    checkpoint = ctx.checkpoint

    logger.warning(
        "[⚠] Max iterations (%d) reached (progress=%s)",
        state.max_iterations,
        state.previous_plan.goal_progress if state.previous_plan else "none",
    )

    # RFC-214: mark the goal's partial work before terminal status is set, so
    # the next goal's planning projection can bound this segment and resume
    # from the last completed step instead of redoing finished work.
    from soothe.sloop.engine.goal_interrupt_record import (
        append_goal_interrupted_ledger_pair,
    )

    await append_goal_interrupted_ledger_pair(
        ctx,
        reason="max_iterations",
        detail=f"iteration limit {state.max_iterations} reached",
    )

    if goal_record is not None:
        goal_record.status = "failed"
        goal_record.completed_at = datetime.now(UTC)
    checkpoint.status = "idle"
    checkpoint.thread_health_metrics.consecutive_goal_failures += 1
    checkpoint.thread_health_metrics.last_goal_status = "failed"
    await state_manager.save(checkpoint)

    result = state.previous_plan or PlanResult(
        status="replan",
        plan_action="new",
        decision=_default_agent_decision(state.goal),
        evidence_summary=state.evidence_summary,
        goal_progress="none",  # IG-399
        next_action="I've hit the iteration limit; I'll pause here.",
    )
    await ctx.emit(
        "completed",
        {
            "result": result,
            "step_results_count": len(state.step_results),
        },
    )
