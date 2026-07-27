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
