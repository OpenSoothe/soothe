"""Resolve executable ``AgentDecision`` from ``PlanResult`` (RFC-220 pre-execute path)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.cognition.plan_dag_normalizer import normalize_plan_dag
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    allocate_plan_id,
    assign_plan_step_ids,
    prepare_decision_for_plan_scoping,
)

from ..orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


def _scope_decision_for_plan(
    decision: AgentDecision,
    state: LoopState,
    *,
    reuse_plan_id: str | None,
) -> AgentDecision:
    """Normalize, generate, and scope step ids for a new or bootstrapped plan."""
    decision = prepare_decision_for_plan_scoping(decision, known_plan_ids=state.known_plan_ids())
    plan_id = reuse_plan_id or allocate_plan_id()
    state.plan_id = plan_id
    decision = assign_plan_step_ids(decision, plan_id=plan_id)
    return normalize_plan_dag(decision, completed_ids=state.dependency_completion_ids())


async def node_resolve_decision(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Generate plan ids, merge keep/new semantics, stash decision on scratch."""
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    plan_result = ctx.scratch.plan_result

    if plan_result is None:
        logger.error("[resolve_decision] missing scratch.plan_result")
        await ctx.emit(
            "fatal_error",
            {"error": "Resolve decision without plan result", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    decision = strange_loop._resolve_decision(plan_result, state)
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
        decision = _scope_decision_for_plan(decision, state, reuse_plan_id=None)
    elif plan_result.plan_action == "keep" and state.current_decision is None:
        decision = _scope_decision_for_plan(decision, state, reuse_plan_id=state.plan_id)

    if plan_result.plan_action == "new":
        state.current_decision = decision

    ctx.scratch.decision = decision
    merged = plan_result.model_copy(update={"decision": decision})
    ctx.scratch.plan_result = merged
    ctx.plan_manager.ingest_plan(merged, state.plan_id, state.iteration)

    # RFC-624 Phase 4: persist CE state after plan ingestion
    if ctx.ce is not None:
        try:
            ctx.ce.defer_save()
        except Exception:
            logger.warning("[resolve_decision] CE save failed", exc_info=True)

    # Calculate cumulative step counts for TUI display
    # done_steps: steps that completed successfully across all iterations
    done_count = sum(1 for r in state.step_results if r.success)
    # total_steps: all steps that have completed (success or fail) + pending new steps
    total_count = len(state.step_results) + len(decision.steps)

    await ctx.emit(
        "plan_decision",
        {
            "iteration": state.iteration,
            "steps": [
                {
                    "id": s.id,
                    "description": (s.description or "").strip().replace("\n", " "),
                    **({"dependencies": list(s.dependencies)} if s.dependencies else {}),
                }
                for s in decision.steps
            ],
            "execution_mode": decision.execution_mode,
            "total_steps": total_count,
            "done_steps": done_count,
        },
    )

    return {}
