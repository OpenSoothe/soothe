"""Terminal handling when ``max_iterations`` is exhausted (RFC-220 ``iteration_gate`` branch)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from soothe.core.agent_loop.state.schemas import PlanResult
from soothe.core.agent_loop.utils.reflection import _default_agent_decision

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def emit_max_iterations_terminal(ctx: LoopRuntimeContext) -> None:
    """Emit failure completion after exhausting iterations (matches legacy AgentLoop)."""
    state = ctx.loop_state
    goal_record = ctx.goal_record
    state_manager = ctx.state_manager
    checkpoint = ctx.checkpoint

    logger.warning(
        "[⚠] Max iterations (%d) reached (progress=%.0f%%)",
        state.max_iterations,
        state.previous_plan.goal_progress * 100 if state.previous_plan else 0,
    )

    if goal_record is not None:
        goal_record.status = "failed"
        goal_record.completed_at = datetime.now(UTC)
    checkpoint.status = "ready_for_next_goal"
    checkpoint.thread_health_metrics.consecutive_goal_failures += 1
    checkpoint.thread_health_metrics.last_goal_status = "failed"
    await state_manager.save(checkpoint)

    result = state.previous_plan or PlanResult(
        status="replan",
        plan_action="new",
        decision=_default_agent_decision(state.goal),
        evidence_summary=state.evidence_summary,
        goal_progress=0.0,
        confidence=0.0,
        next_action="I've hit the iteration limit; I'll pause here.",
    )
    await ctx.emit(
        "completed",
        {
            "result": result,
            "step_results_count": len(state.step_results),
        },
    )
