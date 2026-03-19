"""Plan templates for common task patterns.

Provides template-based planning to avoid LLM calls for routine tasks.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

from soothe.protocols.planner import Plan, PlanStep

logger = logging.getLogger(__name__)


class PlanTemplates:
    """Predefined plan templates for common task patterns.

    Templates are matched via regex patterns for English goals, and can
    fall back to LLM-based intent classification for non-English goals.
    """

    _TEMPLATES: ClassVar[dict[str, Plan]] = {
        "search": Plan(
            goal="",
            steps=[
                PlanStep(
                    id="step_1",
                    description="Use the websearch tool to search the web for relevant, up-to-date information",
                    execution_hint="tool",
                ),
                PlanStep(
                    id="step_2",
                    description="Synthesize the search results into a clear, structured answer",
                    execution_hint="auto",
                    depends_on=["step_1"],
                ),
            ],
        ),
        "analysis": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Analyze the content", execution_hint="auto"),
                PlanStep(
                    id="step_2",
                    description="Provide insights and conclusions",
                    execution_hint="auto",
                    depends_on=["step_1"],
                ),
            ],
        ),
        "implementation": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Understand requirements", execution_hint="auto"),
                PlanStep(
                    id="step_2",
                    description="Implement the solution using workspace and execute tools",
                    execution_hint="tool",
                    depends_on=["step_1"],
                ),
                PlanStep(
                    id="step_3",
                    description="Test and validate using execute tool",
                    execution_hint="tool",
                    depends_on=["step_2"],
                ),
            ],
        ),
    }

    _PATTERNS: ClassVar[list[tuple[str, re.Pattern]]] = [
        ("search", re.compile(r"^(search|find|look up|google)\s+", re.IGNORECASE)),
        ("analysis", re.compile(r"^(analyze|analyse|review|examine|investigate)\s+", re.IGNORECASE)),
        ("implementation", re.compile(r"^(implement|create|build|write|develop)\s+", re.IGNORECASE)),
    ]

    @classmethod
    def match(cls, goal: str) -> Plan | None:
        """Match goal to template via regex patterns.

        Args:
            goal: User's goal text.

        Returns:
            Template plan with goal filled in, or None if no match.
        """
        goal_lower = goal.lower()

        for template_key, pattern in cls._PATTERNS:
            if pattern.match(goal_lower):
                logger.debug("Matched template '%s' for goal: %s", template_key, goal[:50])
                return cls._apply(template_key, goal)

        return None

    @classmethod
    def get(cls, template_key: str) -> Plan | None:
        """Get template by key name.

        Args:
            template_key: Template identifier (question, search, analysis, implementation).

        Returns:
            Template plan, or None if key not found.
        """
        return cls._TEMPLATES.get(template_key)

    @classmethod
    def _apply(cls, template_key: str, goal: str) -> Plan:
        """Create a plan from a template, setting the goal text.

        Args:
            template_key: Template identifier.
            goal: Goal text to set.

        Returns:
            Plan instance copied from template.
        """
        plan = cls._TEMPLATES[template_key].model_copy(deep=True)
        plan.goal = goal
        return plan
