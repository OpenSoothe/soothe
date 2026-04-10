"""Reason phase for Layer 2 ReAct loop (RFC-0008)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.action_quality import enhance_action_specificity
from soothe.cognition.loop_agent.schemas import LoopState, ReasonResult

# Maximum evidence summary length before truncating model-supplied evidence
_EVIDENCE_SUMMARY_MAX_CHARS = 600

if TYPE_CHECKING:
    from soothe.protocols.loop_reasoner import LoopReasonerProtocol
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)


class ReasonPhase:
    """Single LLM call: assess progress and produce the next plan fragment."""

    def __init__(self, loop_reasoner: LoopReasonerProtocol) -> None:
        """Initialize with a ``LoopReasonerProtocol`` implementation."""
        self._loop_reasoner = loop_reasoner

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> ReasonResult:
        """Run Reason and enrich result with evidence and final output when done."""
        evidence_lines = [result.to_evidence_string() for result in state.step_results]
        state.evidence_summary = "\n".join(evidence_lines)

        # LLM tracing - verbose debug logs for reasoning analysis
        logger.debug(
            "[Reason Phase INPUT] ====== Iteration %d START ======",
            state.iteration,
        )
        logger.debug("[Reason Phase INPUT] Goal:\n%s", goal)
        logger.debug(
            "[Reason Phase INPUT] State summary: iteration=%d, max=%d, step_results=%d, completed_steps=%d",
            state.iteration,
            state.max_iterations,
            len(state.step_results),
            len(state.completed_step_ids),
        )
        logger.debug(
            "[Reason Phase INPUT] Wave metrics: tool_calls=%d, subagent_tasks=%d, cap_hit=%s, output_len=%d, errors=%d",
            state.last_wave_tool_call_count,
            state.last_wave_subagent_task_count,
            state.last_wave_hit_subagent_cap,
            state.last_wave_output_length,
            state.last_wave_error_count,
        )
        logger.debug(
            "[Reason Phase INPUT] Action history (size=%d, last 3):\n%s",
            len(state.action_history),
            "\n".join(state.get_recent_actions(3)),
        )

        # Log PlanContext inputs
        logger.debug(
            "[Reason Phase INPUT] Context: workspace=%s, capabilities=%d, completed_steps=%d, prior_msgs=%d",
            context.workspace or "none",
            len(context.available_capabilities),
            len(context.completed_steps),
            len(context.recent_messages),
        )
        logger.debug(
            "[Reason Phase INPUT] Available capabilities:\n%s",
            "\n".join(context.available_capabilities),
        )
        if context.recent_messages:
            logger.debug(
                "[Reason Phase INPUT] Prior messages (%d):\n%s",
                len(context.recent_messages),
                "\n".join(context.recent_messages[:5]),
            )
        if context.completed_steps:
            logger.debug(
                "[Reason Phase INPUT] Completed steps (%d):\n%s",
                len(context.completed_steps),
                "\n".join([f"  {s.step_id}: {s.outcome}" for s in context.completed_steps[:5]]),
            )
        if context.working_memory_excerpt:
            logger.debug(
                "[Reason Phase INPUT] Working memory excerpt:\n%s",
                context.working_memory_excerpt,
            )

        logger.info(
            "[Reason] BEFORE LLM: iteration=%d, history_size=%d, step_results=%d",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )

        result = await self._loop_reasoner.reason(goal=goal, state=state, context=context)

        logger.info(
            "[Reason] AFTER LLM: soothe_next_action from LLM: %s",
            (result.soothe_next_action or "")[:100],
        )

        # LLM tracing - verbose debug logs for reasoning analysis
        logger.debug(
            "[Reason Phase OUTPUT] ====== LLM Response ======",
        )
        logger.debug("[Reason Phase OUTPUT] Status: %s", result.status)
        logger.debug("[Reason Phase OUTPUT] Plan action: %s", result.plan_action)
        logger.debug(
            "[Reason Phase OUTPUT] Progress: %.0f%%, Confidence: %.0f%%",
            result.goal_progress * 100,
            result.confidence * 100,
        )
        logger.debug(
            "[Reason Phase OUTPUT] User summary:\n%s",
            result.user_summary if result.user_summary else "none",
        )
        logger.debug(
            "[Reason Phase OUTPUT] Soothe next action:\n%s",
            result.soothe_next_action if result.soothe_next_action else "none",
        )
        logger.debug(
            "[Reason Phase OUTPUT] Reasoning:\n%s",
            result.reasoning if result.reasoning else "none",
        )
        logger.debug(
            "[Reason Phase OUTPUT] Decision: type=%s, steps=%d, mode=%s",
            result.decision.type if result.decision else "none",
            len(result.decision.steps) if result.decision else 0,
            result.decision.execution_mode if result.decision else "none",
        )
        if result.decision and result.decision.steps:
            logger.debug(
                "[Reason Phase OUTPUT] Decision reasoning:\n%s",
                result.decision.reasoning,
            )
            logger.debug(
                "[Reason Phase OUTPUT] Step descriptions (%d):",
                len(result.decision.steps),
            )
            for i, s in enumerate(result.decision.steps):
                logger.debug(
                    "  Step %d (id=%s): %s",
                    i,
                    s.id,
                    s.description,
                )
                logger.debug(
                    "    Tools: %s, Subagent: %s, Expected: %s",
                    s.tools or "none",
                    s.subagent or "none",
                    s.expected_output,
                )
        logger.debug("[Reason Phase OUTPUT] ====== End LLM Response ======")

        if not result.evidence_summary and state.evidence_summary:
            result = result.model_copy(update={"evidence_summary": state.evidence_summary})

        # Model-supplied evidence can repeat the full assistant answer; that duplicates streamed
        # output and blows the loop.completed one-liner. Prefer compact step-derived evidence.
        _ev = (result.evidence_summary or "").strip()
        _compact = (state.evidence_summary or "").strip()
        if len(_ev) > _EVIDENCE_SUMMARY_MAX_CHARS:
            result = result.model_copy(
                update={"evidence_summary": _compact or f"{_ev[:400].rstrip()}…"},
            )

        if result.is_done():
            full_outputs = [r.to_evidence_string(truncate=False) for r in state.step_results if r.success]
            if full_outputs:
                result = result.model_copy(
                    update={"full_output": "\n\n".join(full_outputs)},
                )

        # RFC-603: Enhance action specificity
        original_action = result.soothe_next_action or ""

        logger.warning(
            "[Action Trace] Iteration %d START:\n  LLM generated: %s\n  Previous actions: %s\n  Step results count: %d",
            state.iteration,
            original_action[:100],
            [a[:50] for a in state.get_recent_actions(3)],
            len(state.step_results),
        )

        enhanced_action = enhance_action_specificity(
            action=original_action,
            _goal=goal,
            iteration=state.iteration,
            previous_actions=state.get_recent_actions(3),
            step_results=state.step_results,
        )

        logger.warning(
            "[Action Trace] Iteration %d ENHANCEMENT:\n  Enhanced: %s\n  Changed: %s",
            state.iteration,
            enhanced_action[:100],
            enhanced_action != original_action,
        )

        # Update result with enhanced action
        if enhanced_action != original_action:
            logger.warning(
                "[Action Enhancement] Iteration %d: Applied enhancement",
                state.iteration,
            )
            # Update BOTH soothe_next_action AND user_summary (pipeline shows user_summary first)
            result = result.model_copy(
                update={
                    "soothe_next_action": enhanced_action,
                    "user_summary": enhanced_action,  # Critical: This is what gets displayed!
                }
            )
        else:
            logger.warning(
                "[Action Enhancement] Iteration %d: No enhancement needed",
                state.iteration,
            )

        # Add to action history
        state.add_action_to_history(enhanced_action)

        logger.warning(
            "[Action Trace] Iteration %d FINAL:\n  Result action: %s\n  History size: %d\n  Last 3 actions: %s",
            state.iteration,
            result.soothe_next_action[:100] if result.soothe_next_action else "None",
            len(state.action_history),
            [a[:50] for a in state.action_history[-3:]],
        )

        successes = sum(1 for r in state.step_results if r.success)
        failures = sum(1 for r in state.step_results if not r.success)
        logger.info(
            "[Reason] status=%s progress=%.0f%% plan_action=%s (evidence steps=%d, ok=%d fail=%d)",
            result.status,
            result.goal_progress * 100,
            result.plan_action,
            len(state.step_results),
            successes,
            failures,
        )

        return result
