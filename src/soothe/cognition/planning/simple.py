"""SimplePlanner -- single LLM call planner for simple/medium tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from soothe.cognition.planning._shared import reflect_heuristic
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_SIMPLE_PLANNER_HINT_MAP = {
    "browser": "subagent",
    "weaver": "subagent",
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


class SimplePlanner:
    """PlannerProtocol using single LLM call for planning.

    For simple/medium tasks. Produces flat plans (typically 1-3 steps).

    Optimizations:
    - Unified planning prompt combines classification + planning
    - Heuristic reflection (no LLM needed)

    Args:
        model: Langchain BaseChatModel supporting structured output.
    """

    def __init__(
        self,
        model: Any,
    ) -> None:
        """Initialize SimplePlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
        """
        self._model = model

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create plan via LLM structured output."""
        # Direct LLM call - no template fallback
        plan = await self._create_plan_via_llm(goal, context)

        # Override execution hints when the user explicitly requested a subagent
        preferred = (
            getattr(context.unified_classification, "preferred_subagent", None)
            if context.unified_classification
            else None
        )
        if preferred:
            plan = self._apply_preferred_subagent(plan, preferred)

        return plan

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
            return Plan(
                goal=goal or "Unnamed goal",
                steps=[{"id": "S_1", "description": goal or "Execute task"}],
            )

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
            return Plan(
                goal=fallback_goal or "Unnamed goal",
                steps=[{"id": "S_1", "description": fallback_goal or "Execute task"}],
            )

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        """Build unified planning prompt with embedded classification."""
        parts = [
            f"Create a plan to accomplish this goal: {goal}\n",
            "\nFirst, classify the intent:",
            "- question: Who/what/how questions needing research",
            "- search: Find/lookup information",
            "- analysis: Analyze/review/examine content",
            "- implementation: Create/build/write code",
            "- debugging: Fix/troubleshoot issues",
            "- compose: Generate custom agent/skill\n",
        ]

        if context.available_capabilities:
            parts.append(f"\nAvailable tools/subagents: {', '.join(context.available_capabilities)}\n")

        parts.extend(
            [
                "\nSpecial routing rules:",
                "- If user explicitly requests a subagent (e.g., 'use browser to...', 'with weaver create...'), ",
                "set execution_hint='subagent' and mention the subagent name in step description",
                "- If goal mentions 'just plan' or 'only planning', set is_plan_only=true\n",
                "\nReturn a JSON object with this exact structure:",
                "{\n",
                '  "goal": "<goal text>",\n',
                '  "is_plan_only": false,\n',
                '  "reasoning": "<brief intent classification>",\n',
                '  "steps": [\n',
                "    {\n",
                '      "id": "S_1",\n',
                '      "description": "<concrete action>",\n',
                '      "execution_hint": "auto"\n',
                "    },\n",
                "    {\n",
                '      "id": "S_2",\n',
                '      "description": "Using the browser subagent, navigate to...",\n',
                '      "execution_hint": "subagent",\n',
                '      "depends_on": ["S_1"]\n',
                "    }\n",
                "  ]\n",
                "}\n\n",
                "Rules:",
                "- Prefer the fewest useful steps; use 1 step when planning is unnecessary",
                "- Usually return 1-3 concrete, actionable steps; only use 4-5 if strictly necessary",
                "- Prefer small, fast-verifiable steps that gather evidence before broad synthesis",
                "- Make each step independently checkable and avoid redundant setup/research steps",
                "- Use depends_on only when a later step truly requires an earlier result",
                "- execution_hint: 'tool' for tool calls, 'subagent' when delegating, 'auto' for LLM reasoning",
                "- Return ONLY valid JSON, no markdown code blocks\n",
            ]
        )

        if context.completed_steps:
            completed_info = "\n".join(
                f"- {step.step_id}: {'success' if step.success else 'failed'} - {step.output}"
                for step in context.completed_steps
            )
            parts.append(f"\nPreviously completed steps:\n{completed_info}\n")

        return "".join(parts)

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

    @staticmethod
    def _apply_preferred_subagent(plan: Plan, subagent_name: str) -> Plan:
        """Override plan execution hints to route through an explicitly requested subagent.

        Skips the first step (typically "understand requirements") and the last
        step if it looks like a summary/validation step, so only the core action
        steps are delegated.

        Args:
            plan: Plan to modify (mutated in place and returned).
            subagent_name: Name of the subagent to delegate to.

        Returns:
            The modified plan.
        """
        action_steps = plan.steps[1:] if len(plan.steps) > 1 else plan.steps
        for step in action_steps:
            if step.execution_hint in ("tool", "auto"):
                step.execution_hint = "subagent"
                lowered = f"{step.description[0].lower()}{step.description[1:]}"
                step.description = f"Using the {subagent_name} subagent, {lowered}"
        logger.info("Applied preferred_subagent=%s to %d step(s)", subagent_name, len(action_steps))
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
