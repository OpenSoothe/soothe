"""JudgeProtocol -- evaluating goal progress during Layer 2 execution (RFC-0008)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class JudgeProtocol(Protocol):
    """Protocol for evaluating goal progress during Layer 2 execution.

    This protocol is used by the JUDGE phase of Layer 2's PLAN → ACT → JUDGE loop
    to evaluate progress toward goal completion based on accumulated evidence
    from step execution.

    Implementations should use evidence accumulation model:
    - Collect all step results (successes and errors)
    - Evaluate overall progress toward goal
    - Decide: "done" (goal achieved), "continue" (strategy valid), or "replan" (need new approach)
    """

    async def judge(
        self,
        goal: str,
        evidence: list[Any],
        steps: list[Any],
    ) -> Any:
        """Evaluate progress toward goal completion.

        Args:
            goal: Goal description to evaluate against.
            evidence: Results from executed steps (list of StepResult).
                     Each result includes success status, output/error, and metadata.
            steps: Steps that were executed (list of StepAction).

        Returns:
            JudgeResult with:
            - status: "continue" | "replan" | "done"
            - evidence_summary: Accumulated evidence text
            - goal_progress: 0.0-1.0 progress toward goal
            - confidence: 0.0-1.0 confidence in judgment
            - reasoning: Explanation of judgment
            - next_steps_hint: Optional hint for next iteration

        Note:
            StepResult, StepAction, and JudgeResult types are defined in
            cognition.loop_agent.schemas to avoid circular imports.

        Implementation Guidelines:
            - Analyze all evidence (both successes and errors)
            - Errors should be evaluated: are they fatal or recoverable?
            - Goal progress should be estimated based on completed work
            - "done" should only be returned when goal is fully achieved
            - "replan" when current strategy clearly won't work
            - "continue" when strategy is valid and making progress
        """
        ...
