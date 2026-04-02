"""Reason phase for Layer 2 ReAct loop (RFC-0008)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.schemas import LoopState, ReasonResult

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

        if result.is_done():
            full_outputs = [r.to_evidence_string(truncate=False) for r in state.step_results if r.success and r.output]
            if full_outputs:
                result = result.model_copy(
                    update={"full_output": "\n\n".join(full_outputs)},
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
