"""Shared utilities for planner backends.

Consolidates duplicate plan parsing and reflection logic used by
ClaudePlanner and SimplePlanner.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from soothe.protocols.planner import (
    GoalContext,
    GoalDirective,
    Plan,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_MIN_STEP_DESCRIPTION_LENGTH = 5

_PLAN_STEP_RE = re.compile(
    r"\*\*Step\s+(\d+)[:\s]*(.+?)\*\*",
    re.IGNORECASE,
)

_PREREQUISITE_PATTERNS = frozenset(
    {
        "missing",
        "not found",
        "not installed",
        "not available",
        "not configured",
        "no such",
        "does not exist",
        "cannot find",
        "dependency",
        "prerequisite",
    }
)


def parse_plan_from_text(goal: str, text: str) -> Plan:
    """Extract a Plan from markdown output (``**Step N: Title**`` format).

    Falls back to numbered/bulleted lines, then to a single-step plan.

    Args:
        goal: The original goal text.
        text: Raw markdown text from a planner.

    Returns:
        Parsed plan with extracted steps.
    """
    steps: list[PlanStep] = []
    matches = _PLAN_STEP_RE.findall(text)
    for i, (_num, title) in enumerate(matches, 1):
        steps.append(PlanStep(id=f"step_{i}", description=title.strip()))

    if not steps:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:10], 1):
            cleaned = re.sub(r"^[\d\-\*\.]+\s*", "", line)
            if cleaned and len(cleaned) > _MIN_STEP_DESCRIPTION_LENGTH:
                steps.append(PlanStep(id=f"step_{i}", description=cleaned))

    if not steps:
        steps = [PlanStep(id="step_1", description=goal)]

    return Plan(goal=goal, steps=steps)


def reflect_heuristic(
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
) -> Reflection:
    """Dependency-aware heuristic reflection (RFC-0010, RFC-0011).

    Categorises failures into direct failures and blocked-by-dependency,
    and optionally generates goal directives for prerequisite issues.

    Args:
        plan: The executed plan.
        step_results: Results from each step.
        goal_context: Optional goal state for directive generation.

    Returns:
        Reflection with assessment and optional goal directives.
    """
    completed = sum(1 for r in step_results if r.success)
    failed_list = [r for r in step_results if not r.success]
    total = len(plan.steps)

    if not failed_list:
        return Reflection(
            assessment=f"{completed}/{total} steps completed successfully",
            should_revise=False,
            feedback="",
            goal_directives=[],
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

    goal_directives = _generate_prerequisite_directives(plan, direct_failed, goal_context)

    return Reflection(
        assessment=". ".join(parts),
        should_revise=True,
        feedback=f"Failed steps: {direct_failed}. Blocked: {blocked}.",
        blocked_steps=blocked,
        failed_details=failed_details,
        goal_directives=goal_directives,
    )


def _generate_prerequisite_directives(
    plan: Plan,
    direct_failed: list[str],
    goal_context: GoalContext | None,
) -> list[GoalDirective]:
    """Generate goal directives for prerequisite failures (RFC-0011).

    Scans the first direct failure for patterns that indicate a missing
    prerequisite and emits a ``create`` directive to spawn a prerequisite goal.
    """
    if not goal_context or not direct_failed:
        return []

    directives: list[GoalDirective] = []
    for step_id in direct_failed[:1]:
        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step or not step.result:
            continue

        result_lower = step.result.lower()
        if any(pattern in result_lower for pattern in _PREREQUISITE_PATTERNS):
            current_priority = 50
            if goal_context.all_goals:
                for g in goal_context.all_goals:
                    if g.get("id") == goal_context.current_goal_id:
                        current_priority = g.get("priority", 50)
                        break

            directives.append(
                GoalDirective(
                    action="create",
                    description=f"Resolve prerequisite for: {step.description[:80]}",
                    priority=min(current_priority + 10, 100),
                    parent_id=None,
                    depends_on=[],
                    rationale=f"Step {step_id} failed due to missing prerequisite",
                )
            )
            break

    return directives


async def reflect_with_llm(
    model: Any,
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
) -> Reflection:
    """LLM-assisted reflection for deeper failure analysis (RFC-0011).

    Uses the heuristic as a fast path for all-success cases. When failures
    exist, invokes the LLM to analyse step results and generate structured
    feedback and goal directives.

    Falls back to ``reflect_heuristic`` if the LLM call fails.

    Args:
        model: A langchain BaseChatModel instance.
        plan: The executed plan.
        step_results: Results from each step.
        goal_context: Optional goal state for directive generation.

    Returns:
        Reflection with LLM-generated assessment and directives.
    """
    failed_list = [r for r in step_results if not r.success]
    if not failed_list:
        completed = sum(1 for r in step_results if r.success)
        return Reflection(
            assessment=f"{completed}/{len(plan.steps)} steps completed successfully",
            should_revise=False,
            feedback="",
            goal_directives=[],
        )

    try:
        prompt = _build_reflection_prompt(plan, step_results, goal_context)
        response = await model.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return _parse_reflection_response(content, plan, step_results, goal_context)
    except Exception:
        logger.debug("LLM-assisted reflection failed, falling back to heuristic", exc_info=True)
        return reflect_heuristic(plan, step_results, goal_context)


def _build_reflection_prompt(
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None,
) -> str:
    """Build a reflection prompt for the LLM."""
    parts = [
        "Analyse the execution results for this plan and provide a structured reflection.",
        f"\nGoal: {plan.goal}",
        "\nStep Results:",
    ]

    for sr in step_results:
        step = next((s for s in plan.steps if s.id == sr.step_id), None)
        desc = step.description if step else sr.step_id
        status = "SUCCESS" if sr.success else "FAILED"
        output_preview = sr.output[:150] if sr.output else "(no output)"
        parts.append(f"  - [{status}] {sr.step_id}: {desc}")
        parts.append(f"    Output: {output_preview}")

    if goal_context:
        parts.append("\nGoal Context:")
        parts.append(f"  Current goal: {goal_context.current_goal_id}")
        parts.append(f"  Completed goals: {goal_context.completed_goals}")
        parts.append(f"  Failed goals: {goal_context.failed_goals}")
        parts.append(f"  Ready goals: {goal_context.ready_goals}")

    parts.append(
        "\nReturn a JSON object with exactly this structure:\n"
        "{\n"
        '  "assessment": "<brief assessment of what happened>",\n'
        '  "should_revise": true/false,\n'
        '  "feedback": "<specific feedback for plan revision>",\n'
        '  "blocked_steps": ["step_id", ...],\n'
        '  "failed_details": {"step_id": "reason", ...},\n'
        '  "goal_directives": [\n'
        "    {\n"
        '      "action": "create|decompose|adjust_priority|add_dependency|fail|complete",\n'
        '      "goal_id": "<target goal id (for existing goals)>",\n'
        '      "description": "<goal description (for create)>",\n'
        '      "priority": <0-100>,\n'
        '      "depends_on": ["goal_id", ...],\n'
        '      "rationale": "<why this directive>"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Set should_revise to true if any step failed\n"
        "- List blocked_steps (steps that failed because their dependency failed)\n"
        "- For prerequisite failures (missing libraries, config, etc.), create a goal directive\n"
        "- Only generate goal_directives when goal_context is provided\n"
        "- Return ONLY valid JSON, NOT wrapped in markdown code blocks"
    )

    return "\n".join(parts)


def _parse_reflection_response(
    content: str,
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None,
) -> Reflection:
    """Parse LLM reflection response into a Reflection model."""
    try:
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        data = json.loads(json_match.group(1)) if json_match else json.loads(content)

        directives = []
        for d in data.get("goal_directives", []):
            try:
                directives.append(GoalDirective(**d))
            except Exception:
                logger.debug("Skipping invalid goal directive: %s", d)

        return Reflection(
            assessment=data.get("assessment", ""),
            should_revise=data.get("should_revise", True),
            feedback=data.get("feedback", ""),
            blocked_steps=data.get("blocked_steps", []),
            failed_details=data.get("failed_details", {}),
            goal_directives=directives,
        )
    except Exception:
        logger.debug("Failed to parse LLM reflection response", exc_info=True)
        return reflect_heuristic(plan, step_results, goal_context)
