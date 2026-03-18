"""AutoPlanner -- hybrid complexity router for PlannerProtocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from soothe.core.classification import (
    classify_by_keywords,
    count_tokens,
)

if TYPE_CHECKING:
    from soothe.protocols.planner import (
        GoalContext,
        Plan,
        PlanContext,
        Reflection,
        StepResult,
    )

logger = logging.getLogger(__name__)

_EXPLICIT_CLAUDE_KEYWORDS = frozenset(
    {
        "use claude",
        "claude plan",
        "deep plan",
        "thorough plan",
    }
)

_COMPLEXITY_PROMPT = """\
Classify the complexity of this task for planning purposes.
Reply with exactly one word: simple, medium, or complex.

Task: {goal}
"""


class AutoPlanner:
    """Hybrid complexity router that delegates to the best available planner.

    Supports three routing modes:
    - ``heuristic``: keyword + token-count only (zero latency)
    - ``llm``: always use fast LLM for classification
    - ``hybrid`` (default): heuristic first; LLM fallback for ambiguous cases

    Routes to:
    - Claude (complex problems, explicit requests)
    - SubagentPlanner (medium complexity)
    - DirectPlanner (simple tasks)

    Args:
        claude: ClaudePlanner instance (or None if unavailable).
        subagent: SubagentPlanner instance (or None if unavailable).
        direct: DirectPlanner instance (or None -- should always be present).
        fast_model: Fast LLM for ambiguity classification (optional).
        routing_mode: Classification strategy.
        simple_token_threshold: Max tokens for simple planning (default: 30).
        complex_token_threshold: Max tokens for complex planning (default: 160).
        use_tiktoken: Use tiktoken for token counting (default: True).
    """

    def __init__(
        self,
        *,
        claude: Any | None = None,
        subagent: Any | None = None,
        direct: Any | None = None,
        fast_model: Any | None = None,
        routing_mode: Literal["heuristic", "llm", "hybrid"] = "hybrid",
        simple_token_threshold: int = 30,
        complex_token_threshold: int = 160,
        use_tiktoken: bool = True,
    ) -> None:
        """Initialize the auto planner with available planner backends.

        Args:
            claude: ClaudePlanner instance (or None if unavailable).
            subagent: SubagentPlanner instance (or None if unavailable).
            direct: DirectPlanner instance (or None -- should always be present).
            fast_model: Fast LLM for ambiguity classification (optional).
            routing_mode: Classification strategy.
            simple_token_threshold: Max tokens for simple planning.
            complex_token_threshold: Max tokens for complex planning.
            use_tiktoken: Use tiktoken for token counting (default: True).
        """
        self._claude = claude
        self._subagent = subagent
        self._direct = direct
        self._fast_model = fast_model
        self._routing_mode = routing_mode
        self._simple_threshold = simple_token_threshold
        self._complex_threshold = complex_token_threshold
        self._use_tiktoken = use_tiktoken

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Route to the best planner based on complexity, then create plan."""
        planner = await self._route(goal)
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

    async def _invoke(self, prompt: str) -> str:
        """Delegate a free-form LLM call to the best available planner."""
        planner = self._best_available()
        return await planner._invoke(prompt)

    async def _route(self, goal: str) -> Any:
        """Determine which planner to use based on ``routing_mode``.

        - ``heuristic``: keyword / word-count only
        - ``llm``: always use ``_llm_classify``
        - ``hybrid``: heuristic first, LLM fallback for ambiguous
        """
        goal_lower = goal.lower()

        if any(kw in goal_lower for kw in _EXPLICIT_CLAUDE_KEYWORDS) and self._claude:
            logger.info("AutoPlanner: explicit Claude request")
            return self._claude

        if self._routing_mode == "llm" and self._fast_model:
            level = await self._llm_classify(goal)
            return self._planner_for_level(level)

        level = self._heuristic_classify(goal)

        if level is None and self._routing_mode == "hybrid" and self._fast_model:
            level = await self._llm_classify(goal)
            logger.info("AutoPlanner: LLM classified ambiguous goal as %s", level)

        return self._planner_for_level(level)

    def _planner_for_level(self, level: str | None) -> Any:
        """Map a complexity level to the best available planner."""
        if level == "complex":
            return self._claude or self._subagent or self._direct
        if level == "medium":
            return self._subagent or self._direct
        if level == "simple":
            return self._direct or self._subagent
        return self._direct or self._subagent

    def _heuristic_classify(self, goal: str) -> str | None:
        """Classify goal complexity using token-based heuristics.

        Returns:
            ``"simple"``, ``"medium"``, ``"complex"``, or ``None`` if ambiguous.
        """
        # Use shared keyword classification
        keyword_result = classify_by_keywords(goal)
        if keyword_result in ("complex", "medium"):
            return keyword_result

        # Map "trivial" to "simple" for planning purposes
        if keyword_result == "trivial":
            return "simple"

        # Token count check (offline, no model needed)
        token_count = count_tokens(goal, use_tiktoken=self._use_tiktoken)

        if token_count >= self._complex_threshold:
            return "complex"

        if token_count < self._simple_threshold:
            return "simple"

        return None

    async def _llm_classify(self, goal: str) -> str:
        """Use a fast LLM call to classify ambiguous goals.

        Language-agnostic since the LLM understands multilingual input.
        """
        try:
            prompt = _COMPLEXITY_PROMPT.format(goal=goal[:500])
            response = await self._fast_model.ainvoke(prompt)
            text = response.content.strip().lower() if hasattr(response, "content") else str(response).strip().lower()
            if "complex" in text:
                return "complex"
            if "medium" in text:
                return "medium"
        except Exception:
            logger.debug("AutoPlanner LLM classification failed", exc_info=True)
            return "medium"
        else:
            return "simple"

    def _best_available(self) -> Any:
        """Return the most capable available planner."""
        return self._claude or self._subagent or self._direct
