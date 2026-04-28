"""User-friendly fallback summary for goal completion (RFC-211, IG-199, IG-299).

Provides simple fallback when synthesis fails or no Execute output exists.
Never leaks internal evidence_summary to users.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult

logger = logging.getLogger(__name__)


def generate_user_fallback_summary(
    state: LoopState,
    plan_result: PlanResult,
) -> str:
    """Generate user-friendly fallback summary (RFC-211 / IG-199 / IG-299).

    NEVER leak internal evidence_summary to users.
    Generate user-friendly completion summary instead.

    Args:
        state: Loop state with step_results.
        plan_result: Plan result with full_output or next_action.

    Returns:
        User-friendly summary text.
    """
    # Use planner's full_output if available
    if plan_result.full_output:
        final_output = plan_result.full_output
        logger.info("Fallback summary: use full_output chars=%d", len(final_output))
        return final_output

    # Generate from step results if available
    if state.step_results:
        successful_count = sum(1 for r in state.step_results if r.success)
        total_count = len(state.step_results)
        final_output = f"Completed {successful_count}/{total_count} steps successfully. {plan_result.next_action or ''}"
        logger.info(
            "Fallback summary: generated from steps success=%d/%d",
            successful_count,
            total_count,
        )
        return final_output

    # No steps executed, use next_action as summary
    final_output = plan_result.next_action or "Goal achieved successfully"
    logger.info("Fallback summary: use next_action chars=%d", len(final_output))
    return final_output
