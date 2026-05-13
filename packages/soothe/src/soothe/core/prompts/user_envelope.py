"""User message envelope builder for execute-step (RFC-214).

Builds the XML envelope that wraps per-turn dynamic content:
- <CURRENT_GOAL> then <USER_QUERY> up front (what to do this turn)
- ``--- Context ---`` then <DYNAMIC_CONTEXT>: execution hints, timestamp, language hint

This envelope keeps volatile content out of the system prompt,
maximizing prompt cache hits.
"""

from __future__ import annotations

import datetime as dt
import re

# Strip legacy AgentLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

# User-visible prose should track the goal's language (execute + plan envelopes, RFC-214).
_RESPONSE_LANGUAGE_HINT = (
    "<response_language_hint>"
    "Prefer the same natural language as the user's goal in this turn for explanations, "
    "summaries, and conclusions; keep code, file paths, identifiers, and quoted literals unchanged."
    "</response_language_hint>"
)

_EXECUTE_STEP_CONTEXT_SEPARATOR = "\n\n--- Context ---\n\n"


def _goal_text_for_execute_step_envelope(goal: str | None) -> str:
    """Normalize goal string for ``<CURRENT_GOAL>`` (strip trailing iteration suffix)."""
    raw = (goal or "").strip()
    if not raw:
        return "No goal specified"
    stripped = _GOAL_ITERATION_SUFFIX_RE.sub("", raw).strip()
    return stripped if stripped else "No goal specified"


def build_execute_step_envelope(
    goal: str | None,
    step_description: str,
    *,
    execution_hints: str | None = None,
    workspace_state: str | None = None,
) -> str:
    """Build the user message envelope for an execute-step (RFC-214).

    The envelope contains all per-turn volatile content that should NOT
    be in the system prompt (date, goal context, execution hints).

    Args:
        goal: Current goal text.
        step_description: The step's description (what to execute).
        execution_hints: Optional hints text from ExecutionHintsMiddleware.
        workspace_state: Optional lightweight workspace diff summary.

    Returns:
        XML envelope string for the LoopHumanMessage content.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    goal_text = _goal_text_for_execute_step_envelope(goal)
    current_goal = f"<CURRENT_GOAL>\n{goal_text}\n</CURRENT_GOAL>"
    user_query = f"<USER_QUERY>\n{step_description}\n</USER_QUERY>"

    # <DYNAMIC_CONTEXT>: hints + context only (goal and step instruction are above the fold)
    dynamic_parts: list[str] = []

    if execution_hints:
        dynamic_parts.append(f"<EXECUTION_HINTS>\n{execution_hints}\n</EXECUTION_HINTS>")

    context_info_parts = [
        f"<timestamp>{timestamp}</timestamp>",
        f"<date>{date_str}</date>",
        _RESPONSE_LANGUAGE_HINT,
    ]
    if workspace_state:
        context_info_parts.append(f"<workspace_state>{workspace_state}</workspace_state>")
    dynamic_parts.append("<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>")

    dynamic_context = "<DYNAMIC_CONTEXT>\n" + "\n".join(dynamic_parts) + "\n</DYNAMIC_CONTEXT>"

    return current_goal + "\n\n" + user_query + _EXECUTE_STEP_CONTEXT_SEPARATOR + dynamic_context


def build_plan_context_envelope(
    goal: str,
    *,
    iteration: int | None = None,
    max_iterations: int | None = None,
    dag_context: str | None = None,
    step_id_hint: str | None = None,
) -> str:
    """Build the user message envelope for plan-assess/plan-generate (RFC-214).

    Similar to execute-step envelope but tailored for plan phase:
    - <GOAL_PROGRESS> instead of <CURRENT_GOAL>
    - Optional <PLAN_STEP_ID_HINT>
    - Optional <PLAN_DAG_CONTEXT>

    Args:
        goal: Current goal text.
        iteration: Current iteration number (1-based for display).
        max_iterations: Maximum iterations allowed.
        dag_context: Optional DAG planning context XML.
        step_id_hint: Optional next step ID hint text.

    Returns:
        XML envelope string for the plan-context LoopHumanMessage.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    # Build <GOAL_PROGRESS>
    iter_display = f"{iteration}/{max_iterations}" if iteration and max_iterations else "?/?"
    goal_progress = (
        f"<GOAL_PROGRESS>\nGoal: {goal}\nExecute iteration: {iter_display}\n</GOAL_PROGRESS>"
    )

    # Optional hints
    extra_parts: list[str] = []
    if step_id_hint:
        extra_parts.append(step_id_hint)
    if dag_context:
        extra_parts.append(dag_context)

    # <CONTEXT_INFO>
    context_info = (
        "<CONTEXT_INFO>\n"
        f"<timestamp>{timestamp}</timestamp>\n"
        f"<date>{date_str}</date>\n"
        f"{_RESPONSE_LANGUAGE_HINT}\n"
        "</CONTEXT_INFO>"
    )

    parts = [goal_progress] + extra_parts + [context_info]
    return "\n".join(parts)
