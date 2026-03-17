"""DirectPlanner -- single LLM call planner for simple tasks."""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

from soothe.protocols.planner import (
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)


class DirectPlanner:
    """PlannerProtocol implementation using a single LLM structured output call.

    For simple/routine tasks. Produces flat plans (typically 1-3 steps).
    Reflection returns a trivial pass-through.

    With RFC-0008 optimizations: Uses template matching for common patterns
    to avoid LLM calls for simple queries.

    Args:
        model: A langchain BaseChatModel instance (or any object supporting
            `with_structured_output` and `ainvoke`).
        use_templates: Enable template matching for common patterns (default: True).
    """

    _PLAN_TEMPLATES: ClassVar[dict[str, Plan]] = {
        "question": Plan(
            goal="",
            steps=[PlanStep(id="step_1", description="", execution_hint="auto")],
        ),
        "search": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Search for information", execution_hint="tool"),
                PlanStep(id="step_2", description="Summarize findings", execution_hint="auto"),
            ],
        ),
        "analysis": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Analyze the content", execution_hint="auto"),
                PlanStep(id="step_2", description="Provide insights", execution_hint="auto"),
            ],
        ),
        "implementation": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Understand requirements", execution_hint="auto"),
                PlanStep(id="step_2", description="Implement the solution", execution_hint="tool"),
                PlanStep(id="step_3", description="Test and validate", execution_hint="tool"),
            ],
        ),
    }

    def __init__(self, model: Any, *, use_templates: bool = True) -> None:
        """Initialize the direct planner.

        Args:
            model: A langchain BaseChatModel instance supporting structured output.
            use_templates: Whether to use template matching (default: True).
        """
        self._model = model
        self._use_templates = use_templates

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan via single LLM call with structured output."""
        # Try template matching first (RFC-0008 Phase 2)
        if self._use_templates:
            template_plan = self._match_template(goal)
            if template_plan:
                logger.info("DirectPlanner: using template plan for: %s", goal[:50])
                return template_plan

        # Fall back to LLM
        structured_model = self._model.with_structured_output(Plan)
        prompt = self._build_plan_prompt(goal, context)
        try:
            plan: Plan = await structured_model.ainvoke(prompt)
        except Exception as e:
            logger.warning("Structured plan creation failed, using fallback: %s", e)
            return Plan(
                goal=goal,
                steps=[PlanStep(id="step_1", description=goal)],
            )
        else:
            return plan

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan based on reflection feedback."""
        structured_model = self._model.with_structured_output(Plan)
        prompt = (
            f"Revise this plan based on the feedback.\n\n"
            f"Current plan goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan."
        )
        try:
            revised: Plan = await structured_model.ainvoke(prompt)
            revised.status = "revised"
        except Exception as e:
            logger.warning("Plan revision failed, keeping original: %s", e)
            return plan
        else:
            return revised

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Trivial reflection for simple plans."""
        completed = sum(1 for r in step_results if r.success)
        failed = sum(1 for r in step_results if not r.success)
        total = len(plan.steps)

        if failed > 0:
            return Reflection(
                assessment=f"{completed}/{total} steps completed, {failed} failed",
                should_revise=True,
                feedback=f"Steps failed: {[r.step_id for r in step_results if not r.success]}",
            )
        return Reflection(
            assessment=f"{completed}/{total} steps completed successfully",
            should_revise=False,
            feedback="",
        )

    def _match_template(self, goal: str) -> Plan | None:
        """Match goal to predefined template.

        Returns None if no match (will use LLM).
        """
        goal_lower = goal.lower()

        # Question patterns
        if re.match(r"^(who|what|where|when|why|how)\s+", goal_lower):
            plan = self._PLAN_TEMPLATES["question"].model_copy(deep=True)
            plan.goal = goal
            plan.steps[0].description = goal
            return plan

        # Search patterns
        if re.match(r"^(search|find|look up|google)\s+", goal_lower):
            plan = self._PLAN_TEMPLATES["search"].model_copy(deep=True)
            plan.goal = goal
            return plan

        # Analysis patterns
        if re.match(r"^(analyze|analyse|review|examine|investigate)\s+", goal_lower):
            plan = self._PLAN_TEMPLATES["analysis"].model_copy(deep=True)
            plan.goal = goal
            return plan

        # Implementation patterns
        if re.match(r"^(implement|create|build|write|develop)\s+", goal_lower):
            plan = self._PLAN_TEMPLATES["implementation"].model_copy(deep=True)
            plan.goal = goal
            return plan

        return None

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        parts = [f"Create a plan to accomplish this goal: {goal}"]
        if context.available_capabilities:
            parts.append(f"Available tools/subagents: {', '.join(context.available_capabilities)}")
        if context.completed_steps:
            parts.append(f"Already completed: {[s.step_id for s in context.completed_steps]}")
        parts.append(
            "Return a JSON object with exactly this structure:\n"
            "{\n"
            '  "goal": "<the goal text>",\n'
            '  "steps": [\n'
            '    {"id": "step_1", "description": "<action>", "execution_hint": "auto|tool|subagent"},\n'
            '    {"id": "step_2", "description": "<action>", "execution_hint": "auto|tool|subagent"}\n'
            "  ]\n"
            "}\n\n"
            "Important: Return the flat structure shown above, NOT nested under a 'plan' key."
        )
        return "\n\n".join(parts)
