"""AutoPlanner -- hybrid complexity router for PlannerProtocol."""

from __future__ import annotations

import logging
import re
from typing import Any

from soothe.protocols.planner import (
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_COMPLEX_KEYWORDS = frozenset(
    {
        "architect",
        "architecture",
        "design system",
        "migrate",
        "migration",
        "refactor entire",
        "redesign",
        "rewrite",
        "overhaul",
        "scale",
        "multi-phase",
        "roadmap",
        "strategy",
        "comprehensive plan",
        "end-to-end",
        "full-stack",
        "infrastructure",
    }
)

_MEDIUM_KEYWORDS = frozenset(
    {
        "plan",
        "implement",
        "build",
        "create feature",
        "add support",
        "integrate",
        "optimise",
        "optimize",
        "debug",
        "investigate",
        "analyse",
        "analyze",
        "review",
        "test suite",
        "refactor",
    }
)

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

    Heuristic pass first; falls back to a fast LLM classifier for ambiguous
    cases. Routes to:
    - Claude (complex problems, explicit requests)
    - SubagentPlanner (medium complexity)
    - DirectPlanner (simple tasks)

    Args:
        claude: ClaudePlanner instance (or None if unavailable).
        subagent: SubagentPlanner instance (or None if unavailable).
        direct: DirectPlanner instance (or None -- should always be present).
        fast_model: Fast LLM for ambiguity classification (optional).
    """

    def __init__(
        self,
        *,
        claude: Any | None = None,
        subagent: Any | None = None,
        direct: Any | None = None,
        fast_model: Any | None = None,
    ) -> None:
        self._claude = claude
        self._subagent = subagent
        self._direct = direct
        self._fast_model = fast_model

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Route to the best planner based on complexity, then create plan."""
        planner = await self._route(goal)
        return await planner.create_plan(goal, context)

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Delegate revision to the best available planner."""
        planner = self._best_available()
        return await planner.revise_plan(plan, reflection)

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Delegate reflection to the best available planner."""
        planner = self._best_available()
        return await planner.reflect(plan, step_results)

    async def _route(self, goal: str) -> Any:
        """Determine which planner to use based on goal complexity."""
        goal_lower = goal.lower()

        if any(kw in goal_lower for kw in _EXPLICIT_CLAUDE_KEYWORDS):
            if self._claude:
                logger.info("AutoPlanner: explicit Claude request")
                return self._claude

        level = self._heuristic_classify(goal)
        if level == "complex":
            return self._claude or self._subagent or self._direct
        if level == "medium":
            return self._subagent or self._direct
        if level == "simple":
            return self._direct or self._subagent

        if self._fast_model:
            level = await self._llm_classify(goal)
            if level == "complex":
                return self._claude or self._subagent or self._direct
            if level == "medium":
                return self._subagent or self._direct
            return self._direct or self._subagent

        return self._subagent or self._direct

    def _heuristic_classify(self, goal: str) -> str | None:
        """Classify goal complexity using heuristics.

        Returns:
            ``"simple"``, ``"medium"``, ``"complex"``, or ``None`` if ambiguous.
        """
        goal_lower = goal.lower()

        if any(kw in goal_lower for kw in _COMPLEX_KEYWORDS):
            return "complex"

        word_count = len(goal.split())
        if word_count > 80:
            return "complex"

        if any(kw in goal_lower for kw in _MEDIUM_KEYWORDS):
            return "medium"

        if word_count < 15:
            return "simple"

        return None

    async def _llm_classify(self, goal: str) -> str:
        """Use a fast LLM call to classify ambiguous goals."""
        try:
            prompt = _COMPLEXITY_PROMPT.format(goal=goal[:500])
            response = await self._fast_model.ainvoke(prompt)
            text = response.content.strip().lower() if hasattr(response, "content") else str(response).strip().lower()
            if "complex" in text:
                return "complex"
            if "medium" in text:
                return "medium"
            return "simple"
        except Exception:
            logger.debug("AutoPlanner LLM classification failed", exc_info=True)
            return "medium"

    def _best_available(self) -> Any:
        """Return the most capable available planner."""
        return self._claude or self._subagent or self._direct
