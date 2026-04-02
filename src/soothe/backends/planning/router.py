"""AutoPlanner -- hybrid complexity router for PlannerProtocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.utils import count_tokens

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.schemas import LoopState
    from soothe.protocols.planner import (
        GoalContext,
        Plan,
        PlanContext,
        Reflection,
        StepResult,
    )

logger = logging.getLogger(__name__)


class AutoPlanner:
    """Hybrid complexity router that delegates to the best available planner.

    Uses pre-computed unified classification from PlanContext (RFC-0012).
    Falls back to token-count heuristics if classification unavailable.

    Routes to:
    - Claude (complex problems)
    - SimplePlanner (medium complexity)

    Args:
        claude: ClaudePlanner instance (or None if unavailable).
        simple: SimplePlanner instance (or None -- should always be present).
        fast_model: Fast LLM (kept for potential future use, unused in RFC-0012).
        medium_token_threshold: Min tokens for medium planning (default: 30).
        complex_token_threshold: Min tokens for complex planning (default: 160).
        use_tiktoken: Use tiktoken for token counting (default: True).
    """

    def __init__(
        self,
        *,
        claude: Any | None = None,
        simple: Any | None = None,
        fast_model: Any | None = None,
        medium_token_threshold: int = 30,
        complex_token_threshold: int = 160,
        use_tiktoken: bool = True,
    ) -> None:
        """Initialize the auto planner with available planner backends.

        Args:
            claude: ClaudePlanner instance (or None if unavailable).
            simple: SimplePlanner instance (or None -- should always be present).
            fast_model: Fast LLM (kept for potential future use, unused in RFC-0012).
            medium_token_threshold: Min tokens for medium planning.
            complex_token_threshold: Min tokens for complex planning.
            use_tiktoken: Use tiktoken for token counting (default: True).
        """
        self._claude = claude
        self._simple = simple
        self._fast_model = fast_model
        self._medium_threshold = medium_token_threshold
        self._complex_threshold = complex_token_threshold
        self._use_tiktoken = use_tiktoken

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Route to the best planner based on unified classification, then create plan."""
        # Use pre-computed unified classification (RFC-0012)
        if context.unified_classification:
            complexity = context.unified_classification.task_complexity
            planner = self._planner_for_level(complexity)
            logger.info("AutoPlanner using unified classification: %s", complexity)
        else:
            # Fallback: shouldn't happen in normal flow
            logger.warning("AutoPlanner: no unified classification, using fallback")
            planner = self._fallback_route(goal)

        return await planner.create_plan(goal, context)

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Delegate revision to the best available planner."""
        planner = self._best_available()
        return await planner.revise_plan(plan, reflection)

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Delegate reflection to the best available planner."""
        planner = self._best_available()
        return await planner.reflect(plan, step_results, goal_context)

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> Any:
        """Delegate Layer 2 Reason phase to SimplePlanner (fast JSON), not Claude agent (RFC-0008)."""
        planner = self._simple or self._best_available()
        return await planner.reason(goal, state, context)

    async def _invoke(self, prompt: str) -> str:
        """Delegate a free-form LLM call (e.g. synthesis) to a lightweight planner.

        Uses SimplePlanner (direct LLM call) rather than ClaudePlanner which
        runs a full agent with tools.  Synthesis only needs summarisation, not
        independent web searches or tool invocations.
        """
        planner = self._simple or self._claude
        if planner is None:
            return ""
        return await planner._invoke(prompt)

    def _fallback_route(self, goal: str) -> Any:
        """Fallback routing using token-count only (NO keywords).

        Used when unified classification is unavailable.
        """
        token_count = count_tokens(goal, use_tiktoken=self._use_tiktoken)

        if token_count >= self._complex_threshold:
            level = "complex"
        elif token_count >= self._medium_threshold:
            level = "medium"
        else:
            level = "medium"  # Default to medium for short queries (chitchat shouldn't reach here)

        return self._planner_for_level(level)

    def _planner_for_level(self, level: str) -> Any:
        """Map a complexity level to the best available planner."""
        if level == "complex":
            return self._claude or self._simple
        if level in ["chitchat", "medium"]:
            # chitchat shouldn't reach here, but fallback to simple if it does
            return self._simple
        return self._simple

    def _best_available(self) -> Any:
        """Return the most capable available planner."""
        return self._claude or self._simple
