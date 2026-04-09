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

        result = await self._loop_reasoner.reason(goal=goal, state=state, context=context)

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
            full_outputs = [r.to_evidence_string(truncate=False) for r in state.step_results if r.success and r.output]
            if full_outputs:
                result = result.model_copy(
                    update={"full_output": "\n\n".join(full_outputs)},
                )

        # RFC-603: Enhance action specificity
        original_action = result.soothe_next_action or ""
        enhanced_action = enhance_action_specificity(
            action=original_action,
            goal=goal,
            iteration=state.iteration,
            previous_actions=state.get_recent_actions(3),
            step_results=state.step_results,
        )

        # Update result with enhanced action
        if enhanced_action != original_action:
            logger.info(
                "[Action Enhancement] Iteration %d: Enhanced action\n  Original: %s\n  Enhanced: %s",
                state.iteration,
                original_action[:80],
                enhanced_action[:80],
            )
            result = result.model_copy(update={"soothe_next_action": enhanced_action})
        else:
            logger.info(
                "[Action Enhancement] Iteration %d: No enhancement needed: %s",
                state.iteration,
                original_action[:80],
            )

        # Add to action history
        state.add_action_to_history(enhanced_action)
        logger.info(
            "[Action History] Iteration %d: History size=%d, Recent=%s",
            state.iteration,
            len(state.action_history),
            [a[:50] for a in state.get_recent_actions(3)],
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
