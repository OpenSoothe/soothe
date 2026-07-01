"""Assess-only planning node (RFC-220 split plan flow).

RFC-226: iter=0 dispatch for continuation queries calls a single
LLM-driven discriminator (``LLMPlanner.assess_continuation``) that
routes to either a terminal bootstrap (one step using prior context)
or the full ``plan_generate`` flow. iter > 0 and fresh-goal iter=0
keep the existing status-check assess.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Literal

from soothe.foundation.sloop.engine.continuation_context import (
    build_continuation_plan_prior_goal_completion,
    build_continue_bootstrap_step_briefs,
    build_prior_goal_summaries,
    polish_continuation_assess_reasoning,
)
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StatusAssessment,
    StepAction,
)
from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)

_PLAN_ASSESS_STATUS_LABEL = "Assessing goal progress"
_PLAN_CONTINUATION_STATUS_LABEL = "Assessing continuation context"


async def _emit_plan_phase_status(
    ctx: LoopRuntimeContext,
    *,
    label: str,
) -> None:
    """Update TUI spinner/status while plan assess or generate LLM calls run."""
    await ctx.emit("plan_phase_status", {"label": label})


# Ordered progress buckets shared by the digest hint and StatusAssessment.goal_progress.
# Used by `_log_prior_progress_disagreement` to compare across the two signals.
_PROGRESS_BUCKETS: tuple[str, ...] = ("none", "low", "medium", "high", "complete")


def _log_prior_progress_disagreement(state: LoopState, assessment: StatusAssessment) -> None:
    """Emit an INFO log when the per-wave digest hint and the LLM disagree.

    Disagreement is defined as the two values being more than one bucket apart
    on the ordered ``_PROGRESS_BUCKETS`` scale. Telemetry only — never overrides
    the assessment.
    """
    digest = state.prior_progress
    if digest is None:
        return
    try:
        hint_idx = _PROGRESS_BUCKETS.index(digest.derived_progress_hint)
        llm_idx = _PROGRESS_BUCKETS.index(assessment.goal_progress)
    except ValueError:
        return
    if abs(hint_idx - llm_idx) > 1:
        logger.info(
            "[Plan] prior_progress hint=%s vs LLM goal_progress=%s (iter=%d)",
            digest.derived_progress_hint,
            assessment.goal_progress,
            state.iteration,
        )


# First-person action descriptions for continue-thread bootstrap (< 15 words each)
_CONTINUE_THREAD_DESCRIPTIONS = [
    "I'll address your follow-up using our conversation context.",
    "I'll continue from where we left off to help you.",
    "I'll respond to your request using prior context.",
    "I'll handle this follow-up based on our earlier work.",
    "I'll proceed with your request from our previous context.",
]


def _has_prior_goal_for_continuation(ctx: LoopRuntimeContext) -> bool:
    """Check CE DAG for prior goal work usable by continuation routing."""
    if ctx.ce is None:
        return False
    current_id = ctx.ce_goal_id
    for goal in ctx.ce.get_all_goals():
        if current_id and goal.id == current_id:
            continue
        completed_steps = [s for s in goal.steps.nodes.values() if s.status == "completed"]
        if completed_steps or goal.action_history:
            return True
        if goal.status in ("completed", "cancelled", "failed"):
            return True
    if ctx.checkpoint and len(ctx.checkpoint.goal_history) >= 2:
        return True
    return False


def _has_prior_completed_goal(ctx: LoopRuntimeContext) -> bool:
    """Check CE DAG for at least one completed prior goal (legacy alias)."""
    return _has_prior_goal_for_continuation(ctx)


def build_continue_loop_bootstrap_plan(
    goal: str,
    *,
    raw_user_goal: str | None = None,
    terminal_after_execute: bool = False,
    reasoning: str = "",
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "low",
) -> PlanResult:
    """Build a synthetic first ``PlanResult`` for loop continuation (RFC-225, RFC-226).

    The executor grounds prior work via ``PRIOR GOAL COMPLETION`` in the execute
    envelope (synthesized prior goal report), not by replaying execute-step ledger rows.

    Args:
        goal: Resolved continuation goal text (often same as ``raw_user_goal``).
        raw_user_goal: Original user submission (e.g. lone ``continue`` keyword).
        terminal_after_execute: When True (RFC-226), the plan asserts its single
            step IS the goal completion; ``record_iteration`` routes directly to
            ``goal_completion`` without an iter=1 status check.
        reasoning: One-sentence assessment reasoning from the discriminator LLM.
        goal_progress: Initial progress estimate.

    Returns:
        ``PlanResult`` with ``status=continue`` and a single parallel step.
    """
    user_goal = (raw_user_goal or goal).strip()
    next_action = random.choice(_CONTINUE_THREAD_DESCRIPTIONS)
    briefs = build_continue_bootstrap_step_briefs(user_goal=user_goal)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description=briefs.description,
                full_description=briefs.full_description,
                expected_output=(
                    "Concrete progress on the recommended next actions from the prior goal "
                    "completion report, without repeating prior goal discovery or analysis."
                ),
            )
        ],
        execution_mode="parallel",
        reasoning="Loop-continuation first-plan bootstrap (no planner LLM).",
    )
    return PlanResult(
        status="continue",
        goal_progress=goal_progress,
        assessment_reasoning=(
            reasoning or "Loop-continuation bootstrap: initial planner call skipped."
        ),
        plan_reasoning="Single execute wave grounded on prior goal completion report.",
        next_action=next_action,
        plan_action="new",
        decision=decision,
        require_goal_completion=False,
        terminal_after_execute=terminal_after_execute,
    )


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    strange_loop = ctx.strange_loop
    strange_loop = strange_loop  # Legacy alias
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    context = strange_loop._build_plan_context(state)

    # RFC-226: iter=0 continuation discriminator.
    # Fires when prior goal context exists, state is a true first plan (no step
    # results), and the structural continue_loop_mode flag is set by StrangeLoop.
    if (
        state.iteration == 0
        and ctx.continue_loop_mode
        and not state.step_results
        and _has_prior_goal_for_continuation(ctx)
        and (
            not ctx.recovery_valid_resume
            or (
                ctx.goal_record is not None
                and ctx.goal_record.iteration == 0
                and ctx.ce is not None
                and len(ctx.ce.ledger.get_messages()) == 0
            )
        )
    ):
        prior_goals = build_prior_goal_summaries(
            ce=ctx.ce,
            checkpoint=ctx.checkpoint,
            exclude_goal_id=ctx.goal_record.goal_id if ctx.goal_record else None,
        )
        if prior_goals:
            await _emit_plan_phase_status(
                ctx,
                label=_PLAN_CONTINUATION_STATUS_LABEL,
            )
            prior_goal_completion = build_continuation_plan_prior_goal_completion(
                loop_messages=state.loop_messages,
                checkpoint=ctx.checkpoint,
                exclude_goal_id=ctx.goal_record.goal_id if ctx.goal_record else None,
            )
            assessment = await strange_loop.loop_planner.assess_continuation(
                current_goal=state.goal,
                prior_goal_completion=prior_goal_completion,
                capabilities=context.available_capabilities,
                thread_id=state.thread_id,
            )
            reason_text = polish_continuation_assess_reasoning(assessment.reasoning or "")
            if assessment.action == "bootstrap":
                logger.info(
                    "[Plan] iter=0 continuation-assess: bootstrap (%s)",
                    reason_text[:120],
                )
                plan_result = build_continue_loop_bootstrap_plan(
                    state.goal,
                    raw_user_goal=state.goal,
                    terminal_after_execute=True,
                    reasoning=reason_text,
                    goal_progress=assessment.goal_progress,
                )
                ctx.scratch.plan_result = plan_result
                ctx.scratch.plan_assessment = None
                if is_continue_keyword(state.goal):
                    await ctx.emit(
                        "plan",
                        {
                            "iteration": state.iteration,
                            "status": plan_result.status,
                            "progress": plan_result.goal_progress,
                            "next_action": "",
                            "assessment_reasoning": "",
                            "plan_reasoning": "",
                            "plan_action": plan_result.plan_action,
                        },
                    )
                else:
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
            # action == "plan_generate": escalate to full planner.
            # Surface discriminator reasoning before plan_generate (RFC-226).
            if reason_text:
                await ctx.emit(
                    "assess",
                    {
                        "assessment_reasoning": reason_text,
                        "iteration": state.iteration,
                    },
                )
            # Build a StatusAssessment from the ContinuationAssessment so the
            # downstream plan_generate node has the payload it requires.
            logger.info(
                "[Plan] iter=0 continuation-assess: plan_generate (%s)",
                reason_text[:120],
            )
            ctx.scratch.plan_assessment = StatusAssessment(
                status="continue",
                goal_progress=assessment.goal_progress,
                assessment_reasoning=reason_text,
                require_goal_completion=False,
            )
            return {"assess_route": "continue_generate"}

    await _emit_plan_phase_status(ctx, label=_PLAN_ASSESS_STATUS_LABEL)
    assessment = await strange_loop.plan_phase.assess_status(
        goal=state.goal,
        state=state,
        context=context,
        context_engine=ctx.ce,
    )
    ctx.scratch.plan_assessment = assessment

    _log_prior_progress_disagreement(state, assessment)

    if assessment.assessment_reasoning:
        await ctx.emit(
            "assess",
            {
                "assessment_reasoning": assessment.assessment_reasoning,
                "iteration": state.iteration,
            },
        )

    if assessment.status == "done":
        if state.has_remaining_steps():
            logger.warning(
                "[Plan] LLM returned status=done but %d step(s) remain; proceeding to goal completion (no new plan will be generated)",
                len(state.current_decision.steps) - len(state.completed_step_ids),
            )

        gc_mode = (
            strange_loop.config.agent.loop.goal_completion_mode
            if strange_loop.config is not None
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
        plan_result = strange_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        # RFC-624 Phase 4: persist CE state after plan ingestion
        if ctx.ce is not None:
            try:
                await ctx.ce.save()
            except Exception:
                logger.warning("[plan_assess] CE save failed", exc_info=True)
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
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
            strange_loop.config.agent.loop.goal_completion_mode
            if strange_loop.config is not None
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
            next_action="Goal progress sufficient for completion",
            require_goal_completion=require_completion,
        )
        plan_result = strange_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        # RFC-624 Phase 4: persist CE state after plan ingestion
        if ctx.ce is not None:
            try:
                await ctx.ce.save()
            except Exception:
                logger.warning("[plan_assess] CE save failed", exc_info=True)
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    return {"assess_route": "continue_generate"}
