"""Goal completion orchestrator module (RFC-615, IG-297).

Main orchestrator for goal completion flow, coordinating categorization,
strategy selection, and execution to produce user-visible completion responses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel

from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

from .completion_strategies import CompletionStrategies
from .response_categorizer import ResponseCategorizer
from .synthesis_executor import SynthesisExecutor

logger = logging.getLogger(__name__)


class GoalCompletionModule:
    """Orchestrates goal completion flow with strategy selection.

    Responsibilities:
    - Coordinate categorization (ResponseCategorizer)
    - Select strategy (CompletionStrategies)
    - Execute strategy (Strategy implementations)
    - Update PlanResult with final output

    Clean Architecture:
    - Orchestration layer (this module)
    - Depends on categorization, strategy, execution layers
    - No direct LLM calls (delegated to executor)
    - No policy logic (delegated to synthesis_policy)

    Integration with AgentLoop:
    - Replaces ~200 lines of goal completion logic in agent_loop.py
    - Provides simple API: complete_goal() → (updated PlanResult, stream)
    - Makes AgentLoop orchestration simpler and testable
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        planner_model: BaseChatModel,
        config: SootheConfig,
    ) -> None:
        """Initialize goal completion module with dependencies.

        Args:
            core_agent: Layer 1 CoreAgent for synthesis execution.
            planner_model: Model instance for goal type classification.
            config: Soothe configuration (for mode settings).
        """
        self.categorizer = ResponseCategorizer(planner_model)
        self.executor = SynthesisExecutor(core_agent)
        self.strategies = CompletionStrategies(self.executor)
        self.config = config

    async def complete_goal(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
    ) -> tuple[PlanResult, AsyncGenerator]:
        """Produce user-visible goal completion response.

        Decision flow:
        1. Categorize response (length, goal type) - ResponseCategorizer
        2. Select strategy (planner_skip, direct, synthesis, summary) - CompletionStrategies
        3. Execute strategy (may involve LLM synthesis) - Strategy implementations
        4. Return updated PlanResult + stream chunks

        Args:
            goal: Goal description for synthesis prompt.
            state: Loop state with execution history and thread context.
            plan_result: Plan result with require_goal_completion recommendation.

        Returns:
            (updated PlanResult with final_output, async generator of stream chunks)
        """
        # 1. Categorize response length and goal type
        category = self.categorizer.categorize(state, plan_result)

        # 2. Select completion strategy
        strategy = self.strategies.select_strategy(state, plan_result, category)

        # 3. Execute strategy
        final_output, stream_gen = await strategy.execute(goal, state, plan_result, category)

        # 4. Update PlanResult with final output
        updated_result = plan_result.model_copy(
            update={
                "full_output": final_output,
                "response_length_category": category.value,
            }
        )

        logger.info(
            "Goal completion module: category=%s strategy=%s output_chars=%d",
            category.value,
            type(strategy).__name__,
            len(final_output or ""),
        )

        return updated_result, stream_gen
