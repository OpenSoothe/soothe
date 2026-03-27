"""Context borrowing for Layer 1 (DeepAgents tool loop).

Generates summaries of Layer 2 state for injection into Layer 1's context.
This enables Layer 1 (tool execution) to see relevant history without
full context explosion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.core.schemas import AgentDecision
    from soothe.cognition.loop_agent.core.state import LoopState


class ContextBorrower:
    """Generate context summaries for Layer 1.

    Implements the Layer 2 → Layer 1 context borrowing protocol:
    - Summarizes previous iterations (not full history)
    - Prevents context explosion
    - Maintains continuity across iterations
    """

    def __init__(self, max_iterations: int = 3, max_chars: int = 500) -> None:
        """Initialize context borrower.

        Args:
            max_iterations: Maximum previous iterations to include
            max_chars: Maximum characters in summary
        """
        self.max_iterations = max_iterations
        self.max_chars = max_chars

    def generate_tool_context(
        self,
        loop_state: LoopState,
        current_decision: AgentDecision,
    ) -> str:
        """Generate context for Layer 1 (DeepAgents graph).

        Args:
            loop_state: Current loop state with history
            current_decision: Current tool being executed

        Returns:
            Summary string to inject into Layer 1's LLM context
        """
        parts = []

        # 1. Current goal context
        parts.append(f"Current goal: {loop_state.goal}")

        # 2. Plan progress (if planning enabled)
        if loop_state.plan:
            completed = sum(1 for s in loop_state.plan.steps if s.status == "completed")
            total = len(loop_state.plan.steps)
            parts.append(f"Plan progress: {completed}/{total} steps")

            # Show which step we're on
            if loop_state.current_step_id:
                current_step = next(
                    (s for s in loop_state.plan.steps if s.id == loop_state.current_step_id),
                    None,
                )
                if current_step:
                    parts.append(f"Current step: {current_step.description[:100]}")

        # 3. Recent iteration summary
        if loop_state.history:
            parts.append("\nRecent iterations:")
            recent = loop_state.history[-self.max_iterations :]

            for record in recent:
                tool = record.decision.tool
                success = record.result.success
                status = "✓" if success else "✗"

                if success:
                    # Show brief result
                    result_preview = record.judgment.reason[:50]
                    parts.append(f"  {status} {tool}: {result_preview}")
                else:
                    # Show error
                    error = record.result.error or "unknown error"
                    parts.append(f"  {status} {tool}: {error[:80]}")

        # 4. Current action context
        parts.append(f"\nNow executing: {current_decision.tool}")
        if current_decision.reasoning:
            parts.append(f"Reason: {current_decision.reasoning[:100]}")

        summary = "\n".join(parts)

        # Truncate to max_chars
        if len(summary) > self.max_chars:
            summary = summary[: self.max_chars - 3] + "..."

        return summary
