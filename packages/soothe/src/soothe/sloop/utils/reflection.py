"""Reflection helpers for agent loop plan parsing and default decisions."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Constants for goal alignment and default decision generation
_GOAL_ALIGN_SNIP_LEN = 400
_DEFAULT_DECISION_GOAL_SNIP_LEN = 350


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
    from soothe.sloop.state.schemas import StepAction

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
    from soothe.sloop.state.schemas import AgentDecision, StepAction

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

        steps.append(
            StepAction(
                id=str(i + 1),
                description=step_data.get("description", ""),
                expected_output=step_data.get("expected_output", ""),
                dependencies=deps,
            )
        )

    _align_step_descriptions(_goal, steps)

    return AgentDecision(
        type=data.get("type", "execute_steps"),
        steps=steps,
        execution_mode=data.get("execution_mode", "parallel"),
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
    from soothe.sloop.state.schemas import AgentDecision, StepAction

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
                id="1",
                description=action_desc,
                expected_output="Concrete findings or artifacts that satisfy the goal",
            )
        ],
        execution_mode="parallel",
        reasoning=f"Default decision due to parse error at iteration {iteration}",
    )


def parse_plan_response_text(response: str, goal: str, iteration: int = 0) -> Any:
    """Parse unified Plan JSON into PlanResult.

    Args:
        response: LLM response text
        goal: Goal description
        iteration: Current iteration number for varied fallback actions
    """
    from soothe.sloop.state.schemas import PlanResult
    from soothe.sloop.utils.json_parsing import _load_llm_json_dict

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

    # Flat plan JSON (steps at root, no status/plan_action)
    if "status" not in data and "steps" in data:
        try:
            decision = agent_decision_from_dict(data, goal)
        except Exception:
            logger.exception("Failed to parse flat plan shape")
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

    # goal_progress: numeric 0.0-1.0 or descriptive level strings
    _raw_gp = data.get("goal_progress", "none")
    if isinstance(_raw_gp, (int, float)):
        _v = float(_raw_gp)
        if _v >= 0.9:
            goal_progress: str = "complete"
        elif _v >= 0.6:
            goal_progress = "high"
        elif _v >= 0.2:
            goal_progress = "medium"
        elif _v > 0:
            goal_progress = "low"
        else:
            goal_progress = "none"
    elif isinstance(_raw_gp, str) and _raw_gp in ("none", "low", "medium", "high", "complete"):
        goal_progress = _raw_gp
    else:
        goal_progress = "none"

    try:
        return PlanResult(
            status=status,
            plan_action=plan_action,
            decision=decision,
            goal_progress=goal_progress,
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
