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

from soothe.foundation.loop.state.checkpoint import GoalExecutionRecord, StrangeLoopCheckpoint
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StatusAssessment,
    StepAction,
)
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)


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


def _prior_goal_summaries(checkpoint: StrangeLoopCheckpoint) -> list[dict]:
    """Compact summary of completed prior goals for the continuation_assess prompt.

    Excludes the active (new) goal at the end of ``goal_history`` and any
    non-completed records. Data is drawn from RFC-225 enrichment fields.

    Args:
        checkpoint: Current StrangeLoopCheckpoint with goal_history.

    Returns:
        List of dicts (one per completed prior goal) with keys:
        ``goal_id``, ``goal_text``, ``completion``, ``step_count``,
        ``current_plan_action``.
    """
    out: list[dict] = []
    for g in checkpoint.goal_history[:-1]:
        if g.status != "completed":
            continue
        out.append(
            {
                "goal_id": g.goal_id,
                "goal_text": g.goal_text,
                "completion": g.goal_completion or "",
                "step_count": len(g.step_results),
                "current_plan_action": (g.current_plan.next_action if g.current_plan else ""),
            }
        )
    return out


def seed_loop_ledger_from_prior_goal(
    checkpoint: StrangeLoopCheckpoint,
    new_goal: GoalExecutionRecord,
    thread_id: str,
) -> None:
    """Copy prior goal context into a new goal's ledger for same-loop follow-ups.

    .. deprecated:: RFC-624 Phase 4 Step 3
        No longer called from ``strange_loop.py`` — CE ledger spans all goals
        via ``ce.load()``. Kept for test compatibility.

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


def build_continue_loop_bootstrap_plan(
    goal: str,
    *,
    terminal_after_execute: bool = False,
    reasoning: str = "",
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "low",
) -> PlanResult:
    """Build a synthetic first ``PlanResult`` for loop continuation (RFC-225, RFC-226).

    The new user request is embedded in the step description so the agent knows
    exactly what to address. The executor additionally prepends the prior goal's
    execute_step ledger entries (seeded into ``LoopState.loop_messages`` by
    ``seed_loop_ledger_from_prior_goal``) as graph_input_messages, giving the
    agent the conversational context it needs to answer.

    Args:
        goal: Loop goal text (the current user request).
        terminal_after_execute: When True (RFC-226), the plan asserts its single
            step IS the goal completion; ``record_iteration`` routes directly to
            ``goal_completion`` without an iter=1 status check.
        reasoning: One-sentence assessment reasoning from the discriminator LLM.
        goal_progress: Initial progress estimate.

    Returns:
        ``PlanResult`` with ``status=continue`` and a single parallel step.
    """
    next_action = random.choice(_CONTINUE_THREAD_DESCRIPTIONS)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description=(
                    "Address the user's request using prior conversation context "
                    f"from earlier goals in this loop: {goal}"
                ),
                expected_output=(
                    "A response that addresses the current request while staying consistent "
                    "with earlier conversation context."
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
        plan_reasoning="Single execute wave from prior loop context and current goal.",
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
    # Only fires when this loop already has at least one completed prior goal,
    # state is a true first plan (no step results, recovery is clean), and
    # the structural continue_loop_mode flag is set by StrangeLoop.
    if (
        state.iteration == 0
        and ctx.continue_loop_mode
        and not state.step_results
        and len(ctx.checkpoint.goal_history) >= 2
        and (
            not ctx.recovery_valid_resume
            or (
                ctx.goal_record is not None
                and ctx.goal_record.iteration == 0
                and not ctx.goal_record.loop_messages
            )
        )
    ):
        prior_goals = _prior_goal_summaries(ctx.checkpoint)
        if prior_goals:
            assessment = await strange_loop.loop_planner.assess_continuation(
                current_goal=state.goal,
                prior_goals=prior_goals,
                capabilities=context.available_capabilities,
                thread_id=state.thread_id,
            )
            reason_text = (assessment.reasoning or "").strip()
            if assessment.action == "bootstrap":
                logger.info(
                    "[Plan] iter=0 continuation-assess: bootstrap (%s)",
                    reason_text[:120],
                )
                plan_result = build_continue_loop_bootstrap_plan(
                    state.goal,
                    terminal_after_execute=True,
                    reasoning=assessment.reasoning,
                    goal_progress=assessment.goal_progress,
                )
                ctx.scratch.plan_result = plan_result
                ctx.scratch.plan_assessment = None
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
                assessment_reasoning=assessment.reasoning,
                require_goal_completion=False,
            )
            return {"assess_route": "continue_generate"}

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
