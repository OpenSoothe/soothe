"""Assess-only planning node (RFC-220 split plan flow).

Continue-thread first-plan bootstrap (IG-325) integrated here.

When intent classification is ``continue_thread`` and loop state is a true
first plan for this run, skip the initial planner LLM and inject a single-step
``PlanResult``. Guards use execution/checkpoint structure only (no query heuristics).
"""

from __future__ import annotations

import logging
import random
from typing import Any

from soothe.core.loop.state.checkpoint import AgentLoopCheckpoint, GoalExecutionRecord
from soothe.core.loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
)
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)


# First-person action descriptions for continue-thread bootstrap (< 15 words each)
_CONTINUE_THREAD_DESCRIPTIONS = [
    "I'll address your follow-up using our conversation context.",
    "I'll continue from where we left off to help you.",
    "I'll respond to your request using prior context.",
    "I'll handle this follow-up based on our earlier work.",
    "I'll proceed with your request from our previous context.",
]


def continue_thread_plan_bootstrap_allowed(
    *,
    continue_thread_mode: bool,
    state: LoopState,
    recovery_valid_resume: bool,
    goal_record: GoalExecutionRecord | None,
) -> bool:
    """Return True when the first Plan call may use a synthetic bootstrap result.

    Args:
        continue_thread_mode: True when intent is ``continue_thread``.
        state: Current loop state (iteration, step_results).
        recovery_valid_resume: True when resuming a running checkpoint with a valid
            ``GoalExecutionRecord`` (not the invalid-index re-init path).
        goal_record: Active goal record when in recovery, else the new goal record
            from ``start_new_goal`` on a fresh run.

    Returns:
        Whether bootstrap is structurally allowed.
    """
    if not continue_thread_mode:
        return False
    if state.iteration != 0:
        return False
    if state.step_results:
        return False

    if recovery_valid_resume:
        if goal_record is None:
            return False
        if goal_record.iteration != 0:
            return False
        if goal_record.loop_messages:
            return False

    return True


def seed_continue_thread_ledger_from_prior_goal(
    checkpoint: AgentLoopCheckpoint,
    new_goal: GoalExecutionRecord,
    thread_id: str,
) -> None:
    """Copy prior goal context into a new goal's ledger for same-loop follow-ups.

    When ``loop_id`` is stable per conversation thread, the new goal starts with an
    empty ``loop_messages`` list while Execute prompts still reference the RFC-214
    ledger. Reuse the previous completed goal's ledger, or fall back to
    ``goal_completion`` text when the ledger was not persisted.

    Args:
        checkpoint: Loaded checkpoint whose ``goal_history`` ends with ``new_goal``.
        new_goal: The goal record just appended for this user turn (last in history).
        thread_id: Active conversation thread id for message metadata.
    """
    history = checkpoint.goal_history
    if len(history) < 2:
        return
    prev = history[-2]
    if prev.status != "completed":
        return
    if prev.loop_messages:
        new_goal.loop_messages.extend(m.model_copy(deep=True) for m in prev.loop_messages)
        return
    completion = (prev.goal_completion or "").strip()
    if not completion:
        return
    gtext = prev.goal_text or "Previous request"
    new_goal.loop_messages.extend(
        [
            LoopHumanMessage(
                content=gtext,
                thread_id=thread_id,
                iteration=0,
                goal_summary=gtext[:200] if gtext else None,
                phase=None,
            ),
            LoopAIMessage(
                content=completion,
                thread_id=thread_id,
                iteration=0,
                phase=None,
            ),
        ]
    )


def build_continue_thread_bootstrap_plan(_goal: str) -> PlanResult:
    """Build a synthetic first ``PlanResult`` for continue-thread (IG-325, RFC-214).

    The loop goal is the user's current request on ``LoopState.goal``; prior turns
    are supplied via ``loop_messages`` ledger for Execute prompts (RFC-214).

    Args:
        _goal: Loop goal text (reserved for callers; body uses ``LoopState``).

    Returns:
        ``PlanResult`` with ``status=continue`` and a single sequential step.
    """
    next_action = random.choice(_CONTINUE_THREAD_DESCRIPTIONS)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description="Address follow-up request using prior conversation context.",
                expected_output=(
                    "A response that addresses the current request while staying consistent "
                    "with earlier conversation context."
                ),
            )
        ],
        execution_mode="sequential",
        reasoning="Continue-thread first-plan bootstrap (no planner LLM).",
    )
    return PlanResult(
        status="continue",
        goal_progress="low",  # IG-399: descriptive level (initial bootstrap)
        assessment_reasoning="Continue-thread bootstrap: initial planner call skipped.",
        plan_reasoning="Single execute wave from thread context and loop goal.",
        next_action=next_action,
        plan_action="new",
        decision=decision,
        require_goal_completion=False,
    )


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    context = agent_loop._build_plan_context(state)

    if continue_thread_plan_bootstrap_allowed(
        continue_thread_mode=ctx.continue_thread_mode,
        state=state,
        recovery_valid_resume=ctx.recovery_valid_resume,
        goal_record=ctx.goal_record,
    ):
        logger.info("[Plan] iter=0 continue-thread bootstrap (no planner LLM)")
        plan_result = build_continue_thread_bootstrap_plan(state.goal)
        ctx.scratch.plan_result = plan_result
        ctx.scratch.plan_assessment = None
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"assess_route": "skip_generate"}

    assessment = await agent_loop.plan_phase.assess_status(
        goal=state.goal,
        state=state,
        context=context,
    )
    ctx.scratch.plan_assessment = assessment

    if assessment.status == "done":
        if state.has_remaining_steps():
            logger.warning(
                "[Plan] LLM returned status=done but %d step(s) remain; proceeding to goal completion (no new plan will be generated)",
                len(state.current_decision.steps) - len(state.completed_step_ids),
            )

        gc_mode = (
            agent_loop.config.agent_loop.goal_completion_mode
            if agent_loop.config is not None
            else "llm_only"
        )
        require_completion = plan_manager.determine_goal_completion_needs(
            llm_decision=assessment.require_goal_completion,
            state=state,
            mode=gc_mode,
        )
        plan_result = PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning="",
            plan_reasoning="",
            plan_action="keep",
            decision=None,
            next_action="Goal achieved successfully",
            require_goal_completion=require_completion,
            full_output=state.last_execute_assistant_text,
        )
        plan_result = agent_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    # goal_progress-based early routing: when progress is complete, go to goal completion
    if assessment.goal_progress == "complete":
        logger.info(
            "[Plan] goal_progress=%s routing to goal completion",
            assessment.goal_progress,
        )
        gc_mode = (
            agent_loop.config.agent_loop.goal_completion_mode
            if agent_loop.config is not None
            else "llm_only"
        )
        require_completion = plan_manager.determine_goal_completion_needs(
            llm_decision=assessment.require_goal_completion,
            state=state,
            mode=gc_mode,
        )
        plan_result = PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning=assessment.assessment_reasoning or "",
            plan_reasoning="",
            plan_action="keep",
            decision=None,
            next_action="Goal progress sufficient for completion",
            require_goal_completion=require_completion,
        )
        plan_result = agent_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    return {"assess_route": "continue_generate"}
