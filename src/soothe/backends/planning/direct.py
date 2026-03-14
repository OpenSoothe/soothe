"""DirectPlanner -- single LLM call planner for simple tasks."""

from __future__ import annotations

import logging
from typing import Any

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

    Args:
        model: A langchain BaseChatModel instance (or any object supporting
            `with_structured_output` and `ainvoke`).
    """

    def __init__(self, model: Any) -> None:
        self._model = model

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan via single LLM call with structured output."""
        structured_model = self._model.with_structured_output(Plan)
        prompt = self._build_plan_prompt(goal, context)
        try:
            plan: Plan = await structured_model.ainvoke(prompt)
            return plan
        except Exception:
            logger.warning("Structured plan creation failed, using fallback")
            return Plan(
                goal=goal,
                steps=[PlanStep(id="step_1", description=goal)],
            )

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
            return revised
        except Exception:
            logger.warning("Plan revision failed, keeping original")
            return plan

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

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        parts = [f"Create a plan to accomplish this goal: {goal}"]
        if context.available_capabilities:
            parts.append(f"Available tools/subagents: {', '.join(context.available_capabilities)}")
        if context.completed_steps:
            parts.append(f"Already completed: {[s.step_id for s in context.completed_steps]}")
        parts.append(
            "Return a Plan with concrete, actionable steps. "
            "Each step should have an id (step_1, step_2, ...), "
            "description, and execution_hint."
        )
        return "\n\n".join(parts)
