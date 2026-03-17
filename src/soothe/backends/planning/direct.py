"""DirectPlanner -- single LLM call planner for simple tasks."""

from __future__ import annotations

import json
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
        prompt = self._build_plan_prompt(goal, context)

        # Try structured output first
        try:
            structured_model = self._model.with_structured_output(Plan)
            plan: Plan = await structured_model.ainvoke(prompt)
            # Post-process to fix execution_hint values if needed
            return self._normalize_execution_hints(plan)
        except Exception as e:
            logger.warning("Structured plan creation failed, trying manual parse: %s", e)

            # Try manual parsing as fallback
            try:
                response = await self._model.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                plan = self._parse_json_from_response(content, goal)
                if plan:
                    return plan
            except Exception as manual_error:
                logger.warning("Manual parse also failed: %s", manual_error)

            # Ultimate fallback
            return Plan(
                goal=goal,
                steps=[PlanStep(id="step_1", description=goal)],
            )

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan based on reflection feedback."""
        prompt = (
            f"Revise this plan based on the feedback.\n\n"
            f"Current plan goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan."
        )

        try:
            structured_model = self._model.with_structured_output(Plan)
            revised: Plan = await structured_model.ainvoke(prompt)
            revised.status = "revised"
            # Post-process to fix execution_hint values if needed
            return self._normalize_execution_hints(revised)
        except Exception as e:
            logger.warning("Plan revision failed, trying manual parse: %s", e)

            # Try manual parsing as fallback
            try:
                response = await self._model.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                revised = self._parse_json_from_response(content, plan.goal)
                if revised:
                    revised.status = "revised"
                    return revised
            except Exception as manual_error:
                logger.warning("Manual parse also failed: %s", manual_error)

            return plan

    def _parse_json_from_response(self, content: str, goal: str) -> Plan | None:  # noqa: ARG002
        """Parse Plan from LLM response content.

        Handles JSON wrapped in markdown code blocks.
        """
        try:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                data = json.loads(json_str)
                # Normalize hints in dict before creating Plan
                data = self._normalize_hints_in_dict(data)
                return Plan(**data)

            # Try direct JSON parse
            data = json.loads(content)
            # Normalize hints in dict before creating Plan
            data = self._normalize_hints_in_dict(data)
            return Plan(**data)
        except Exception as parse_error:
            logger.debug("JSON parse failed: %s", parse_error)
            return None

    def _normalize_hints_in_dict(self, data: dict) -> dict:
        """Normalize execution_hint values in a dict before creating Plan.

        Args:
            data: Dictionary with 'steps' key containing step dicts.

        Returns:
            Modified dict with normalized execution_hint values.
        """
        hint_mapping = {
            "scout": "subagent",
            "browser": "subagent",
            "research": "subagent",
            "weaver": "subagent",
            "skillify": "subagent",
            "search": "tool",
            "web": "tool",
            "api": "tool",
        }

        if "steps" in data:
            for step in data["steps"]:
                if "execution_hint" in step:
                    hint = step["execution_hint"]
                    if hint not in ("tool", "subagent", "remote", "auto"):
                        normalized = hint_mapping.get(hint, "auto")
                        logger.warning(
                            "Normalizing invalid execution_hint '%s' to '%s'",
                            hint,
                            normalized,
                        )
                        step["execution_hint"] = normalized

        return data

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Dependency-aware reflection (RFC-0010)."""
        completed = sum(1 for r in step_results if r.success)
        failed_list = [r for r in step_results if not r.success]
        total = len(plan.steps)

        if not failed_list:
            return Reflection(
                assessment=f"{completed}/{total} steps completed successfully",
                should_revise=False,
                feedback="",
            )

        failed_ids = {r.step_id for r in failed_list}
        blocked: list[str] = []
        direct_failed: list[str] = []
        for r in failed_list:
            step = next((s for s in plan.steps if s.id == r.step_id), None)
            if step and any(dep in failed_ids for dep in step.depends_on):
                blocked.append(r.step_id)
            else:
                direct_failed.append(r.step_id)

        failed_details = {r.step_id: (r.output[:200] if r.output else "no output") for r in failed_list}

        parts = [f"{completed}/{total} steps completed, {len(failed_list)} failed"]
        if direct_failed:
            parts.append(f"Directly failed: {direct_failed}")
        if blocked:
            parts.append(f"Blocked by dependencies: {blocked}")

        logger.debug(
            "Reflection: completed=%d failed=%d blocked=%d direct_failed=%d",
            completed,
            len(failed_list),
            len(blocked),
            len(direct_failed),
        )
        return Reflection(
            assessment=". ".join(parts),
            should_revise=True,
            feedback=f"Failed steps: {direct_failed}. Blocked: {blocked}.",
            blocked_steps=blocked,
            failed_details=failed_details,
        )

    async def _invoke(self, prompt: str) -> str:
        """Run a free-form LLM call and return the text response."""
        response = await self._model.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

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
            '    {"id": "step_1", "description": "<action>", "execution_hint": "auto"},\n'
            '    {"id": "step_2", "description": "<action>", "execution_hint": "tool"}\n'
            "  ]\n"
            "}\n\n"
            "IMPORTANT execution_hint rules:\n"
            "- Must be one of: 'tool', 'subagent', 'remote', 'auto'\n"
            "- Use 'tool' for tool-based operations\n"
            "- Use 'subagent' for delegating to specialized subagents\n"
            "- Use 'auto' for LLM reasoning or synthesis\n"
            "- Do NOT use other values like 'scout', 'browser', 'research', etc.\n\n"
            "Important: Return the flat structure shown above, NOT nested under a 'plan' key. "
            "Return ONLY valid JSON, NOT wrapped in markdown code blocks."
        )
        return "\n\n".join(parts)

    def _normalize_execution_hints(self, plan: Plan) -> Plan:
        """Normalize execution_hint values to valid options.

        Some LLMs may return invalid hints like 'scout', 'browser', etc.
        This method maps them to valid values.
        """
        # Map common invalid values to valid ones
        hint_mapping = {
            "scout": "subagent",
            "browser": "subagent",
            "research": "subagent",
            "weaver": "subagent",
            "skillify": "subagent",
            "search": "tool",
            "web": "tool",
            "api": "tool",
        }

        for step in plan.steps:
            if step.execution_hint not in ("tool", "subagent", "remote", "auto"):
                original = step.execution_hint
                # Try to map to a valid value
                normalized = hint_mapping.get(original, "auto")
                logger.warning(
                    "Normalizing invalid execution_hint '%s' to '%s' for step %s",
                    original,
                    normalized,
                    step.id,
                )
                step.execution_hint = normalized

        return plan
