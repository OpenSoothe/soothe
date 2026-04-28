"""Reflection and goal alignment logic for agent loop.

Provides dependency-aware heuristic reflection and LLM-assisted failure analysis.
Generates goal directives for prerequisite failures and manages agent decisions.
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
    Reflection,
    StepResult,
)
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

# Constants for goal alignment and default decision generation
_GOAL_ALIGN_SNIP_LEN = 400
_DEFAULT_DECISION_GOAL_SNIP_LEN = 350

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


def reflect_heuristic(
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
) -> Reflection:
    """Dependency-aware heuristic reflection (RFC-0010, RFC-0007 §5.4).

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

    failed_details = {
        r.step_id: (preview_first(r.to_evidence_string(), 200) if not r.success else "no output")
        for r in failed_list
    }

    parts = [f"{completed}/{total} steps completed, {len(failed_list)} failed"]
    if direct_failed:
        parts.append(f"Directly failed: {direct_failed}")
    if blocked:
        parts.append(f"Blocked by dependencies: {blocked}")

    logger.debug(
        "[Reflect] completed=%d failed=%d blocked=%d direct=%d",
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
    """Generate goal directives for prerequisite failures (RFC-0007 §5.4).

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
                    description=f"Resolve prerequisite for: {preview_first(step.description, 80)}",
                    priority=min(current_priority + 10, 100),
                    parent_id=None,
                    depends_on=[],
                    rationale=f"S_{step_id} failed due to missing prerequisite",
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
    """LLM-assisted reflection for deeper failure analysis (RFC-0007 §5.4).

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
        # IG-143: Add metadata for tracing
        from soothe.middleware._utils import create_llm_call_metadata

        prompt = _build_reflection_prompt(plan, step_results, goal_context)
        response = await model.ainvoke(
            prompt,
            config={
                "metadata": create_llm_call_metadata(
                    purpose="reflection",
                    component="planning._shared",
                    phase="post-loop",
                )
            },
        )
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
        output_preview = preview_first(sr.to_evidence_string(), 150)
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


def _extract_text_content(content: Any) -> str:
    """Normalise LLM response content to a plain string.

    Handles both the simple string case and the Anthropic-style list-of-blocks
    case (e.g. ``[{'type': 'text', 'text': '...'}, {'type': 'tool_use', ...}]``).

    Args:
        content: The ``content`` attribute from a LangChain AIMessage.

    Returns:
        Plain text, joining all ``text``-type blocks when content is a list.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


def _align_step_descriptions(goal: str, steps: list[Any]) -> None:
    """Rewrite step text that only echoes the user goal without concrete actions."""
    from soothe.cognition.agent_loop.state.schemas import StepAction

    g = (goal or "").strip().casefold()
    if not g:
        return
    for s in steps:
        if not isinstance(s, StepAction):
            continue
        d = (s.description or "").strip()
        if d.casefold() == g:
            lim = _GOAL_ALIGN_SNIP_LEN
            tail = goal if len(goal) <= lim else goal[: lim - 3] + "…"
            s.description = (
                "Using tools in the open workspace, take concrete actions toward this goal "
                f"(do not use the goal text alone as the step): {tail}"
            )


def agent_decision_from_dict(data: dict[str, Any], _goal: str) -> Any:
    """Build AgentDecision from a parsed JSON object (step list at top level)."""
    from soothe.cognition.agent_loop.state.schemas import AgentDecision, StepAction

    known_subagents = {"browser", "claude", "explore", "research"}

    steps = []
    for i, step_data in enumerate(data.get("steps", [])):
        if not isinstance(step_data, dict):
            continue
        deps = step_data.get("dependencies")
        deps = (
            []
            if deps is None or not isinstance(deps, list)
            else [str(d) for d in deps if d is not None]
        )

        tools = step_data.get("tools") or []
        if tools:
            subagent_tools = [t for t in tools if t in known_subagents]
            if subagent_tools:
                if not step_data.get("subagent"):
                    step_data["subagent"] = subagent_tools[0]
                    logger.debug(
                        "Normalized subagent '%s' from tools to subagent field", subagent_tools[0]
                    )
                remaining_tools = [t for t in tools if t not in known_subagents]
                step_data["tools"] = remaining_tools or None

        steps.append(
            StepAction(
                id=f"step_{i}",
                description=step_data.get("description", ""),
                tools=step_data.get("tools"),
                subagent=step_data.get("subagent"),
                expected_output=step_data.get("expected_output", ""),
                dependencies=deps,
            )
        )

    _align_step_descriptions(_goal, steps)

    return AgentDecision(
        type=data.get("type", "execute_steps"),
        steps=steps,
        execution_mode=data.get("execution_mode", "sequential"),
        reasoning=data.get("reasoning", ""),
        adaptive_granularity=data.get("adaptive_granularity"),
    )


def _default_agent_decision(goal: str, iteration: int = 0) -> Any:
    """Minimal single-step decision used when parsing fails.

    Args:
        goal: The goal description
        iteration: Current iteration number for variation

    Returns:
        AgentDecision with iteration-specific action to prevent repetitions
    """
    from soothe.cognition.agent_loop.state.schemas import AgentDecision, StepAction

    lim = _DEFAULT_DECISION_GOAL_SNIP_LEN
    tail = goal if len(goal) <= lim else goal[: lim - 3] + "…"

    # RFC-603: Vary the default action based on iteration to prevent repetitions
    if iteration == 0:
        action_desc = f"Take initial steps toward: {tail}"
    elif iteration == 1:
        action_desc = f"Continue investigation with focused approach for: {tail}"
    else:
        action_desc = f"Refine approach for: {tail}"

    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="step_0",
                description=action_desc,
                expected_output="Concrete findings or artifacts that satisfy the goal",
            )
        ],
        execution_mode="sequential",
        reasoning=f"Default decision due to parse error at iteration {iteration}",
    )


def parse_plan_response_text(response: str, goal: str, iteration: int = 0) -> Any:
    """Parse unified Plan JSON into PlanResult.

    Args:
        response: LLM response text
        goal: Goal description
        iteration: Current iteration number for varied fallback actions
    """
    from soothe.cognition.agent_loop.state.schemas import PlanResult
    from soothe.cognition.agent_loop.utils.json_parsing import _load_llm_json_dict

    try:
        data = _load_llm_json_dict(response)
    except Exception:
        logger.exception("[PARSE ERROR] Failed to parse LLM response")
        return PlanResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal, iteration),
            next_action="I'll try again with a simpler plan.",
        )

    # Legacy flat plan (steps at root, no plan fields)
    if "status" not in data and "steps" in data:
        try:
            decision = agent_decision_from_dict(data, goal)
        except Exception:
            logger.exception("Failed to parse legacy plan shape")
            decision = _default_agent_decision(goal, iteration)
        return PlanResult(
            status="continue",
            plan_action="new",
            decision=decision,
            next_action="I'll run the steps in this plan next.",
        )

    status = data.get("status", "replan")
    if status not in ("continue", "replan", "done"):
        status = "replan"

    plan_action = data.get("plan_action", "new")
    if plan_action not in ("keep", "new"):
        plan_action = "new"

    next_action = str(data.get("next_action", "") or "").strip()

    decision = None
    if plan_action == "new":
        raw_decision = data.get("decision")
        if isinstance(raw_decision, dict):
            try:
                decision = agent_decision_from_dict(raw_decision, goal)
            except Exception:
                logger.exception("Failed to parse nested decision")
                decision = _default_agent_decision(goal, iteration) if status != "done" else None
        elif status != "done":
            decision = _default_agent_decision(goal, iteration)

    if plan_action == "keep":
        decision = None

    try:
        return PlanResult(
            status=status,
            plan_action=plan_action,
            decision=decision,
            goal_progress=float(data.get("goal_progress", 0.0)),
            confidence=float(data.get("confidence", 0.8)),
            next_action=next_action,
            evidence_summary=str(data.get("evidence_summary", "") or ""),
        )
    except Exception:
        logger.exception("Invalid PlanResult fields")
        return PlanResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal, iteration),
            next_action="I'll adjust and try a cleaner plan.",
        )
