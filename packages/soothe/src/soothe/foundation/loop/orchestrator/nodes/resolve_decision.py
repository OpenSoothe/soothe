"""Resolve executable ``AgentDecision`` from ``PlanResult`` (RFC-220 pre-execute path)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    StepAction,
    allocate_plan_id,
    assign_plan_step_ids,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_resolve_decision(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Allocate plan ids, merge keep/new semantics, stash decision on scratch."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_result = ctx.scratch.plan_result

    if plan_result is None:
        logger.error("[resolve_decision] missing scratch.plan_result")
        await ctx.emit(
            "fatal_error",
            {"error": "Resolve decision without plan result", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    decision = agent_loop._resolve_decision(plan_result, state)
    if decision is None:
        # Guard: create fallback decision when LLM returned type="final" at iteration 0
        if state.iteration == 0 and len(state.step_results) == 0:
            logger.warning("[Guard] No decision at iter=0; creating fallback execute plan")
            decision = AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(
                        id="01",
                        description=state.goal or "Execute task",
                    )
                ],
                execution_mode="parallel",
                reasoning="Initial execution to gather evidence for goal assessment",
            )
        else:
            logger.error("[Reason] No executable decision after reason phase; aborting loop")
            await ctx.emit(
                "fatal_error",
                {"error": "Reason phase returned no executable plan", "step_id": ""},
            )
            return {"last_outcome": "fatal"}

    if plan_result.plan_action == "new":
        reserved = set(state.dependency_completion_ids())
        plan_id = allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)
    elif plan_result.plan_action == "keep" and state.current_decision is None:
        reserved = set(state.dependency_completion_ids())
        plan_id = state.plan_id or allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)

    if plan_result.plan_action == "new":
        state.completed_step_ids.clear()
        state.current_decision = decision
        # RFC-225: count plan revisions in the active goal record
        if ctx.goal_record is not None:
            ctx.goal_record.plan_revision_count += 1

    ctx.scratch.decision = decision
    merged = plan_result.model_copy(update={"decision": decision})
    ctx.scratch.plan_result = merged
    ctx.plan_manager.ingest_plan(merged, state.plan_id, state.iteration)

    await ctx.emit(
        "plan_decision",
        {
            "iteration": state.iteration,
            "steps": [
                {
                    "id": s.id,
                    "description": (s.description or "").strip().replace("\n", " "),
                }
                for s in decision.steps
            ],
            "execution_mode": decision.execution_mode,
        },
    )

    return {}
