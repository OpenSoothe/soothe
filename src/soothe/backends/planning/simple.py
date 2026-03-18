"""SimplePlanner -- single LLM call planner for simple tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, ClassVar

from soothe.backends.planning._shared import reflect_heuristic
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_INTENT_CLASSIFY_PROMPT = """\
Classify this user request into exactly one category.
Reply with a single word: question, search, analysis, or implementation.

Request: {goal}
"""


class SimplePlanner:
    """PlannerProtocol implementation using a single LLM structured output call.

    For simple/routine tasks. Produces flat plans (typically 1-3 steps).

    With RFC-0008 optimizations: Uses template matching for common patterns
    to avoid LLM calls for simple queries.

    Args:
        model: A langchain BaseChatModel instance (or any object supporting
            `with_structured_output` and `ainvoke`).
        use_templates: Enable template matching for common patterns (default: True).
        fast_model: Optional fast LLM for intent classification of non-English goals.
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

    def __init__(
        self,
        model: Any,
        *,
        use_templates: bool = True,
        fast_model: Any | None = None,
    ) -> None:
        """Initialize the simple planner.

        Args:
            model: A langchain BaseChatModel instance supporting structured output.
            use_templates: Whether to use template matching (default: True).
            fast_model: Optional fast LLM for non-English intent classification.
        """
        self._model = model
        self._use_templates = use_templates
        self._fast_model = fast_model

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan via single LLM call with structured output."""
        if self._use_templates:
            template_plan = await self._match_template(goal)
            if template_plan:
                logger.info("SimplePlanner: using template plan for: %s", goal[:50])
                return template_plan

        prompt = self._build_plan_prompt(goal, context)

        try:
            structured_model = self._model.with_structured_output(Plan)
            plan: Plan = await structured_model.ainvoke(prompt)
            return self._normalize_execution_hints(plan)
        except Exception as e:
            logger.warning("Structured plan creation failed, trying manual parse: %s", e)

            try:
                response = await self._model.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                plan = self._parse_json_from_response(content, goal)
                if plan:
                    return plan
            except Exception as manual_error:
                logger.warning("Manual parse also failed: %s", manual_error)

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
            return self._normalize_execution_hints(revised)
        except Exception as e:
            logger.warning("Plan revision failed, trying manual parse: %s", e)

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
            json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                data = json.loads(json_str)
                data = self._normalize_hints_in_dict(data)
                return Plan(**data)

            data = json.loads(content)
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

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Dependency-aware reflection using shared heuristic (RFC-0010, RFC-0011)."""
        return reflect_heuristic(plan, step_results, goal_context)

    async def _invoke(self, prompt: str) -> str:
        """Run a free-form LLM call and return the text response."""
        response = await self._model.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    async def _match_template(self, goal: str) -> Plan | None:
        """Match goal to predefined template.

        Tries English regex patterns first (zero cost). Falls back to
        fast-model intent classification for non-English goals.

        Returns None if no match (will use full LLM).
        """
        goal_lower = goal.lower()

        if re.match(r"^(who|what|where|when|why|how)\s+", goal_lower):
            return self._apply_template("question", goal)

        if re.match(r"^(search|find|look up|google)\s+", goal_lower):
            return self._apply_template("search", goal)

        if re.match(r"^(analyze|analyse|review|examine|investigate)\s+", goal_lower):
            return self._apply_template("analysis", goal)

        if re.match(r"^(implement|create|build|write|develop)\s+", goal_lower):
            return self._apply_template("implementation", goal)

        # Non-English / ambiguous: use fast model for intent classification
        if self._fast_model:
            intent = await self._classify_intent(goal)
            if intent and intent in self._PLAN_TEMPLATES:
                logger.info("SimplePlanner: fast-model classified intent as '%s'", intent)
                return self._apply_template(intent, goal)

        return None

    def _apply_template(self, template_key: str, goal: str) -> Plan:
        """Create a plan from a template, setting the goal text."""
        plan = self._PLAN_TEMPLATES[template_key].model_copy(deep=True)
        plan.goal = goal
        if template_key == "question":
            plan.steps[0].description = goal
        return plan

    async def _classify_intent(self, goal: str) -> str | None:
        """Classify goal intent via fast LLM (language-agnostic)."""
        try:
            prompt = _INTENT_CLASSIFY_PROMPT.format(goal=goal[:300])
            response = await self._fast_model.ainvoke(prompt)
            text = response.content.strip().lower() if hasattr(response, "content") else str(response).strip().lower()
            for category in ("question", "search", "analysis", "implementation"):
                if category in text:
                    return category
        except Exception:
            logger.debug("SimplePlanner intent classification failed", exc_info=True)
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
                normalized = hint_mapping.get(original, "auto")
                logger.warning(
                    "Normalizing invalid execution_hint '%s' to '%s' for step %s",
                    original,
                    normalized,
                    step.id,
                )
                step.execution_hint = normalized

        return plan
