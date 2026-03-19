"""SimplePlanner -- single LLM call planner for simple/medium tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from soothe.backends.planning._shared import reflect_heuristic
from soothe.backends.planning._templates import PlanTemplates
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_SIMPLE_PLANNER_HINT_MAP = {
    "scout": "subagent",
    "browser": "subagent",
    "research": "subagent",
    "weaver": "subagent",
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


class SimplePlanner:
    """PlannerProtocol using single LLM call with optional templates.

    For simple/medium tasks. Produces flat plans (typically 1-3 steps).

    Optimizations:
    - Template matching for common patterns (avoids LLM calls)
    - Pre-computed template intent from UnifiedClassification
    - Heuristic reflection (no LLM needed)

    Args:
        model: Langchain BaseChatModel supporting structured output.
        use_templates: Enable template matching (default: True).
    """

    def __init__(
        self,
        model: Any,
        *,
        use_templates: bool = True,
    ) -> None:
        """Initialize SimplePlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
            use_templates: Enable template matching (default: True).
        """
        self._model = model
        self._use_templates = use_templates

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create plan via template matching or LLM structured output."""
        # Try template matching first
        if self._use_templates:
            # Try regex-based template matching
            if template := PlanTemplates.match(goal):
                logger.info("Using template plan for: %s", goal[:50])
                return template

            # Try pre-computed template intent from unified classification
            if (
                context.unified_classification
                and hasattr(context.unified_classification, "template_intent")
                and context.unified_classification.template_intent
                and (template := PlanTemplates.get(context.unified_classification.template_intent))
            ):
                logger.info(
                    "Using pre-classified template '%s' for: %s",
                    context.unified_classification.template_intent,
                    goal[:50],
                )
                return template

        # Fallback to LLM structured output
        return await self._create_plan_via_llm(goal, context)

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise plan based on reflection feedback."""
        prompt = self._build_revision_prompt(plan, reflection)

        try:
            structured_model = self._model.with_structured_output(Plan)
            revised = await structured_model.ainvoke(prompt)
            revised.status = "revised"
            return self._normalize_hints(revised)
        except Exception as e:
            logger.warning("Plan revision failed: %s", e)
            return plan

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Heuristic reflection (no LLM needed for simple plans)."""
        return reflect_heuristic(plan, step_results, goal_context)

    async def _invoke(self, prompt: str) -> str:
        """Invoke the LLM with a free-form prompt and return the response.

        Used for synthesis and other LLM-based operations.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            The LLM's response as a string.
        """
        try:
            response = await self._model.ainvoke(prompt)
            content = getattr(response, "content", str(response))
            return content if isinstance(content, str) else str(content)
        except Exception as e:
            logger.warning("SimplePlanner._invoke failed: %s", e)
            return ""

    async def _create_plan_via_llm(self, goal: str, context: PlanContext) -> Plan:
        """Create plan via LLM structured output with fallback parsing."""
        prompt = self._build_plan_prompt(goal, context)

        try:
            structured_model = self._model.with_structured_output(Plan)
            plan = await structured_model.ainvoke(prompt)
            return self._normalize_hints(plan)
        except Exception as e:
            logger.warning("Structured output failed, trying manual parse: %s", e)
            return await self._fallback_parse(goal, prompt)

    async def _fallback_parse(self, goal: str, prompt: str) -> Plan:
        """Fallback plan parsing from raw LLM response."""
        try:
            response = await self._model.ainvoke(prompt)
            content = getattr(response, "content", str(response))
            return self._parse_json_from_response(content, goal)
        except Exception as e:
            logger.warning("Fallback parsing failed: %s", e)
            return Plan(goal=goal, steps=[{"id": "step_1", "description": goal}])

    def _parse_json_from_response(self, content: str, fallback_goal: str) -> Plan:
        """Parse Plan from JSON content, optionally wrapped in markdown.

        Args:
            content: JSON string, optionally wrapped in ```json``` markdown block
            fallback_goal: Goal to use if parsing fails

        Returns:
            Parsed Plan object or fallback single-step plan
        """
        try:
            # Try JSON extraction from markdown code blocks
            if json_match := re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL):
                data = json.loads(json_match.group(1))
                return Plan(**self._normalize_hints_in_dict(data))

            # Try plain JSON
            data = json.loads(content)
            return Plan(**self._normalize_hints_in_dict(data))
        except Exception as e:
            logger.warning("JSON parsing failed: %s", e)
            return Plan(goal=fallback_goal, steps=[{"id": "step_1", "description": fallback_goal}])

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        """Build planning prompt."""
        parts = [f"Create a plan to accomplish this goal: {goal}"]

        if context.available_capabilities:
            parts.append(f"Available tools/subagents: {', '.join(context.available_capabilities)}")

        if context.completed_steps:
            completed_info = "\n".join(
                f"- {step.step_id}: {'success' if step.success else 'failed'} - {step.output}"
                for step in context.completed_steps
            )
            parts.append(f"Previously completed steps:\n{completed_info}")

        parts.append(
            "Return a JSON object with this structure:\n"
            "{\n"
            '  "goal": "<goal text>",\n'
            '  "steps": [\n'
            '    {"id": "step_1", "description": "<action>", "execution_hint": "auto"}\n'
            "  ]\n"
            "}\n\n"
            "execution_hint must be one of: 'tool', 'subagent', 'remote', 'auto'\n"
            "Return ONLY valid JSON, no markdown code blocks."
        )
        return "\n\n".join(parts)

    def _build_revision_prompt(self, plan: Plan, reflection: str) -> str:
        """Build plan revision prompt."""
        return (
            f"Revise this plan based on feedback.\n\n"
            f"Goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan with the same JSON structure."
        )

    def _normalize_hints(self, plan: Plan) -> Plan:
        """Normalize execution_hint values to valid options."""
        for step in plan.steps:
            if step.execution_hint not in ("tool", "subagent", "remote", "auto"):
                original = step.execution_hint
                step.execution_hint = _SIMPLE_PLANNER_HINT_MAP.get(original, "auto")
                logger.warning("Normalized hint '%s' to '%s'", original, step.execution_hint)

        return plan

    def _normalize_hints_in_dict(self, data: dict) -> dict:
        """Normalize execution_hint in dict before Plan creation."""
        if "steps" in data:
            for step in data["steps"]:
                if "execution_hint" in step:
                    hint = step["execution_hint"]
                    if hint not in ("tool", "subagent", "remote", "auto"):
                        step["execution_hint"] = _SIMPLE_PLANNER_HINT_MAP.get(hint, "auto")
        return data
