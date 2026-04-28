"""Completion strategy implementations for goal completion (RFC-615, IG-297).

Strategy pattern for different goal completion approaches, separating strategy selection
from execution and making completion logic extensible.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from soothe.cognition.agent_loop.policies.response_length_policy import ResponseLengthCategory
from soothe.cognition.agent_loop.policies.synthesis_policy import (
    needs_final_thread_synthesis,
    should_return_goal_completion_directly,
)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from .synthesis_executor import SynthesisExecutor

logger = logging.getLogger(__name__)


class CompletionStrategy(Protocol):
    """Protocol for completion strategy implementations.

    Each strategy represents a different approach to producing user-visible
    goal completion text, following the strategy pattern for extensibility.
    """

    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Execute strategy and return final output + stream chunks.

        Args:
            goal: Goal description.
            state: Loop state with execution history.
            plan_result: Plan result with planner recommendations.
            length_category: Response length category.

        Returns:
            (final_output_text, async_generator_of_stream_chunks)
        """
        ...


async def _empty_generator() -> AsyncGenerator:
    """Helper for strategies that don't stream."""
    return
    yield  # Makes this an async generator


class PlannerSkipStrategy:
    """Reuse Execute assistant text when planner says no synthesis needed.

    Triggered when plan_result.require_goal_completion == False,
    indicating planner has determined Execute output is sufficient.
    """

    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Reuse last Execute assistant text.

        Args:
            goal: Goal description (unused for this strategy).
            state: Loop state with last_execute_assistant_text.
            plan_result: Plan result (unused for this strategy).
            length_category: Response length category (unused for this strategy).

        Returns:
            (reused_assistant_text, empty_generator)
        """
        _ = goal, plan_result, length_category  # Unused

        reuse = (state.last_execute_assistant_text or "").strip()
        logger.info("Goal completion: branch=planner_skip assistant_chars=%d", len(reuse))
        return reuse, _empty_generator()


class DirectReturnStrategy:
    """Direct return when Execute output is rich and aligned with planner output.

    Triggered when should_return_goal_completion_directly() returns True,
    indicating Execute output satisfies richness and overlap criteria.
    """

    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Reuse last Execute assistant text directly.

        Args:
            goal: Goal description (unused for this strategy).
            state: Loop state with last_execute_assistant_text.
            plan_result: Plan result (unused for this strategy).
            length_category: Response length category (unused for this strategy).

        Returns:
            (reused_assistant_text, empty_generator)
        """
        _ = goal, plan_result, length_category  # Unused

        reuse = (state.last_execute_assistant_text or "").strip()
        logger.info("Goal completion: branch=direct assistant_chars=%d", len(reuse))
        return reuse, _empty_generator()


class SynthesisStrategy:
    """Execute LLM synthesis turn for comprehensive final report.

    Triggered when needs_final_thread_synthesis() returns True,
    indicating evidence heuristics or planner request synthesis.
    """

    def __init__(self, executor: SynthesisExecutor) -> None:
        """Initialize synthesis strategy with executor.

        Args:
            executor: SynthesisExecutor for LLM calls.
        """
        self.executor = executor

    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Execute LLM synthesis and return final text.

        Args:
            goal: Goal description for synthesis prompt.
            state: Loop state with thread context.
            plan_result: Plan result with evidence.
            length_category: Response length category for guidance.

        Returns:
            (synthesis_text, stream_generator)
        """
        # Execute synthesis - executor returns final text + stream generator
        final_text, stream_gen = await self.executor.execute_synthesis(
            goal, state, plan_result, length_category
        )

        return final_text, stream_gen


class SummaryStrategy:
    """Fallback summary from plan_result or step counts.

    Triggered when other strategies don't apply, providing user-friendly
    summary without LLM synthesis.
    """

    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Generate summary from plan_result or step counts.

        Args:
            goal: Goal description (unused for this strategy).
            state: Loop state with step_results.
            plan_result: Plan result with full_output or next_action.
            length_category: Response length category (unused for this strategy).

        Returns:
            (summary_text, empty_generator)
        """
        _ = goal, length_category  # Unused

        # RFC-211 / IG-199: Goal completion — fallback summary
        # NEVER leak internal evidence_summary to users
        # Generate user-friendly summary instead when full_output is empty
        if plan_result.full_output:
            final_output = plan_result.full_output
        elif state.step_results:
            # Generate user-friendly completion summary from successful steps
            successful_count = sum(1 for r in state.step_results if r.success)
            total_count = len(state.step_results)
            final_output = f"Completed {successful_count}/{total_count} steps successfully. {plan_result.next_action or ''}"
        else:
            # No steps executed, use next_action as summary
            final_output = plan_result.next_action or "Goal achieved successfully"

        logger.info("Goal completion: branch=summary chars=%d", len(final_output or ""))
        return final_output, _empty_generator()


class CompletionStrategies:
    """Strategy selection and execution for goal completion.

    Responsibilities:
    - Select appropriate strategy based on policy decisions
    - Initialize strategies with dependencies (executor)
    - Honor planner recommendations (IG-295 fix)

    Decision tree:
    1. planner_skip: when planner says no synthesis needed
    2. direct: when Execute output is rich and aligned
    3. synthesis: when evidence heuristics request synthesis
    4. summary: fallback when other strategies don't apply
    """

    def __init__(self, executor: SynthesisExecutor) -> None:
        """Initialize strategies with executor.

        Args:
            executor: SynthesisExecutor for synthesis strategy.
        """
        self.executor = executor

    def select_strategy(
        self,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
        mode: str = "adaptive",
    ) -> CompletionStrategy:
        """Select completion strategy based on policy decisions.

        Priority (IG-295 fix honored):
        1. Planner recommendation (require_goal_completion)
        2. Evidence heuristics (synthesis policy)
        3. Fallback summary

        Args:
            state: Loop state with execution history.
            plan_result: Plan result with planner recommendations.
            length_category: Response length category.
            mode: Final-response mode (adaptive, always_synthesize, always_last_execute).

        Returns:
            Selected strategy instance ready for execution.
        """
        # IG-295: Honor planner's explicit goal completion request
        # Planner sets require_goal_completion=True when:
        # - Word count < 150 (low richness)
        # - High evidence volume with moderate output
        # - Other heuristics indicate synthesis needed

        if not plan_result.require_goal_completion:
            # Planner says Execute output is sufficient → skip synthesis
            return PlannerSkipStrategy()

        # Check if Execute output can be returned directly
        if should_return_goal_completion_directly(
            state,
            plan_result,
            mode,
            response_length_category=length_category.value,
        ):
            return DirectReturnStrategy()

        # Check if synthesis is needed (IG-295 fix: honors require_goal_completion)
        if needs_final_thread_synthesis(state, plan_result, mode):
            return SynthesisStrategy(self.executor)

        # Fallback: summary from plan_result or step counts
        return SummaryStrategy()
