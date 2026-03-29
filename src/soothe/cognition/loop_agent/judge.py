"""JUDGE phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.schemas import JudgeResult, LoopState

if TYPE_CHECKING:
    from soothe.protocols.judge import JudgeProtocol

logger = logging.getLogger(__name__)


class JudgePhase:
    """JUDGE phase: Evaluate goal progress.

    This component evaluates progress toward goal completion using
    evidence accumulation from all executed steps (both successes and errors).
    """

    def __init__(self, judge: JudgeProtocol) -> None:
        """Initialize JUDGE phase.

        Args:
            judge: Judge protocol implementation
        """
        self._judge_impl = judge  # Renamed to avoid collision with method

    async def judge(
        self,
        goal: str,
        state: LoopState,
    ) -> JudgeResult:
        """Evaluate progress toward goal completion.

        Evidence accumulation:
        - Collect all step results (successes and errors)
        - Build evidence summary
        - Call JudgeProtocol to evaluate

        Args:
            goal: Goal description
            state: Current loop state

        Returns:
            JudgeResult with status, progress, and reasoning
        """
        # Build evidence summary (truncated for logging)
        evidence_lines = [result.to_evidence_string() for result in state.step_results]
        evidence_summary = "\n".join(evidence_lines)

        # Build full output for final response (not truncated)
        full_outputs = [
            result.to_evidence_string(truncate=False)
            for result in state.step_results
            if result.success and result.output
        ]

        # Get executed steps
        steps = state.current_decision.steps if state.current_decision else []

        # Log evidence before judgment
        successes = sum(1 for r in state.step_results if r.success)
        failures = sum(1 for r in state.step_results if not r.success)

        logger.info(
            "Judging goal progress - %d steps executed (%d success, %d failed)",
            len(state.step_results),
            successes,
            failures,
        )

        # Call judge protocol
        judgment = await self._judge_impl.judge(
            goal=goal,
            evidence=state.step_results,
            steps=steps,
        )

        # Update state with evidence
        state.evidence_summary = evidence_summary

        # Attach full output to judgment for display
        if full_outputs and judgment.is_done():
            # Use the most recent substantial output as the final response
            judgment.full_output = "\n\n".join(full_outputs)

        # Log judgment result
        logger.info(
            "Judgment: status=%s progress=%.0f%% confidence=%.0f%% - %s",
            judgment.status,
            judgment.goal_progress * 100,
            judgment.confidence * 100,
            judgment.reasoning[:100],
        )

        return judgment
