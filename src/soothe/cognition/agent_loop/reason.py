"""Reason phase for Layer 2 ReAct loop (RFC-0008)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.schemas import LoopState, ReasonResult

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

        # --- Debug: pre-LLM snapshot ---
        logger.debug(
            "[Reason] iter=%d | goal=%.80s | steps=%d ok=%d fail=%d | "
            "wave: calls=%d sub=%d cap=%s out=%d err=%d | "
            "ctx: caps=%d msgs=%d done=%d",
            state.iteration,
            goal,
            len(state.step_results),
            len(state.completed_step_ids),
            0,
            state.last_wave_tool_call_count,
            state.last_wave_subagent_task_count,
            state.last_wave_hit_subagent_cap,
            state.last_wave_output_length,
            state.last_wave_error_count,
            len(context.available_capabilities),
            len(context.recent_messages),
            len(context.completed_steps),
        )
        if context.available_capabilities:
            logger.debug("[Reason] caps: %s", ", ".join(context.available_capabilities))
        if context.recent_messages:
            logger.debug(
                "[Reason] recent_msgs(%d): %s",
                len(context.recent_messages),
                " | ".join(context.recent_messages[:3]),
            )
        if context.completed_steps:
            logger.debug(
                "[Reason] done_steps(%d): %s",
                len(context.completed_steps),
                ", ".join(f"{s.step_id}={s.outcome}" for s in context.completed_steps[:5]),
            )
        if context.working_memory_excerpt:
            logger.debug("[Reason] mem: %.200s", context.working_memory_excerpt)
        if state.action_history:
            logger.debug(
                "[Reason] actions(%d): %s",
                len(state.action_history),
                " | ".join(state.get_recent_actions(3)),
            )

        logger.info(
            "[Reason] iter=%d calling LLM (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )

        result = await self._loop_reasoner.reason(goal=goal, state=state, context=context)

        # --- Debug: post-LLM snapshot ---
        logger.debug(
            "[Reason] LLM out: status=%s plan=%s progress=%.0f%% conf=%.0f%% action=%.100s",
            result.status,
            result.plan_action,
            result.goal_progress * 100,
            result.confidence * 100,
            (result.soothe_next_action or "none")[:100],
        )
        if result.reasoning:
            logger.debug("[Reason] reasoning: %.300s", result.reasoning)
        if result.decision:
            step_summary = ", ".join(f"{s.id}={s.description[:40]}" for s in result.decision.steps[:5])
            logger.debug(
                "[Reason] decision: type=%s mode=%s steps=%d [%s]",
                result.decision.type,
                result.decision.execution_mode,
                len(result.decision.steps),
                step_summary,
            )

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

        # Track action in history (used by completion detection)
        state.add_action_to_history(result.soothe_next_action or "")

        successes = sum(1 for r in state.step_results if r.success)
        failures = sum(1 for r in state.step_results if not r.success)
        logger.info(
            "[Reason] iter=%d done: status=%s progress=%.0f%% plan=%s (steps=%d ok=%d fail=%d)",
            state.iteration,
            result.status,
            result.goal_progress * 100,
            result.plan_action,
            len(state.step_results),
            successes,
            failures,
        )

        return result
