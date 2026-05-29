"""User message envelope builder for execute-step (RFC-214).

Builds the XML envelope that wraps per-turn dynamic content:
- <USER_QUERY> up front (what to do this turn)
- Slash-skill turns: optional ``<SKILL_CONTEXT>`` after ``<USER_QUERY>`` (skill reference
  only, not the full expanded goal prompt)
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

# Shown inside <USER_PRIMARY_QUERY> when /skill: expanded but the user gave no trailing text.
_EMPTY_SKILL_USER_TEXT_PLACEHOLDER = (
    "(No free-text instruction after the skill selector — follow the full goal and skill "
    "reference below.)"
)


def _slash_skill_trailing_user_text(goal_user_submission: str | None) -> str | None:
    """Return trailing args for a ``/skill:`` submission, or ``None`` if not a skill line.

    When this is not ``None`` (including empty string for ``/skill:name`` with no args),
    envelope builders split primary user text from long expanded skill content.

    Args:
        goal_user_submission: Original user line saved on ``LoopState`` when a skill expands.

    Returns:
        ``None`` if ``submission`` is missing or not a slash-skill line; otherwise the
        text after the skill token (may be empty).
    """
    if not goal_user_submission or not str(goal_user_submission).strip():
        return None
    from soothe.skills.catalog import parse_slash_skill_user_line

    parsed = parse_slash_skill_user_line(str(goal_user_submission).strip())
    if parsed is None:
        return None
    return parsed[1]


def _goal_text_for_execute_step_envelope(goal: str | None) -> str:
    """Normalize goal string for slash-skill ``<FULL_GOAL_AND_SKILL_CONTEXT>`` (strip iteration suffix)."""
    raw = (goal or "").strip()
    if not raw:
        return "No goal specified"
    stripped = _GOAL_ITERATION_SUFFIX_RE.sub("", raw).strip()
    return stripped if stripped else "No goal specified"


def _append_project_instructions_to_context_info(
    context_info_parts: list[str],
    project_instructions: str | None,
) -> None:
    if project_instructions:
        context_info_parts.append(project_instructions)


def build_execute_step_envelope(
    step_description: str,
    *,
    execution_hints: str | None = None,
    workspace_state: str | None = None,
    project_instructions: str | None = None,
    skill_context: str | None = None,
) -> str:
    """Build the user message envelope for an execute-step (RFC-214).

    The envelope contains all per-turn volatile content that should NOT
    be in the system prompt (date, execution hints, optional skill reference).

    Args:
        step_description: The step's description (what to execute).
        execution_hints: Optional hints text from ExecutionHintsMiddleware.
        workspace_state: Optional lightweight workspace diff summary.
        project_instructions: Optional ``<project_instructions>`` XML from workspace
            ``CLAUDE.md`` / ``AGENTS.md`` (first N lines).
        skill_context: Skill reference only (SKILL.md); omitted when not a slash-skill turn.

    Returns:
        XML envelope string for the LoopHumanMessage content.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    user_query = f"<USER_QUERY>\n{step_description}\n</USER_QUERY>"

    body_parts: list[str] = [user_query]
    skill_ref = (skill_context or "").strip()
    if skill_ref:
        body_parts.append(f"<SKILL_CONTEXT>\n{skill_ref}\n</SKILL_CONTEXT>")

    # <DYNAMIC_CONTEXT>: hints + context only (step instruction is above the fold)
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
    _append_project_instructions_to_context_info(context_info_parts, project_instructions)
    dynamic_parts.append("<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>")

    dynamic_context = "<DYNAMIC_CONTEXT>\n" + "\n".join(dynamic_parts) + "\n</DYNAMIC_CONTEXT>"

    return "\n\n".join(body_parts) + _EXECUTE_STEP_CONTEXT_SEPARATOR + dynamic_context


def build_plan_context_envelope(
    goal: str,
    *,
    dag_context: str | None = None,
    step_id_hint: str | None = None,
    project_instructions: str | None = None,
    goal_user_submission: str | None = None,
    skill_context: str | None = None,
) -> str:
    """Build the user message envelope for plan-assess/plan-generate (RFC-214).

    Similar to execute-step envelope but tailored for plan phase:
    - <GOAL_PROGRESS> instead of <CURRENT_GOAL>
    - Optional <SKILL_REFERENCE> when slash-skill invoked (body injected once per turn)
    - Optional <PLAN_STEP_ID_HINT>
    - Optional <PLAN_DAG_CONTEXT>

    Args:
        goal: Current goal text.
        dag_context: Optional DAG planning context XML.
        step_id_hint: Optional next step ID hint text.
        project_instructions: Optional ``<project_instructions>`` XML from workspace
            ``CLAUDE.md`` / ``AGENTS.md`` (plan-generate only at call sites).
        goal_user_submission: Original ``/skill:`` line when applicable; used to surface
            the short user query before long expanded skill content.
        skill_context: Skill reference body for ``<SKILL_REFERENCE>`` when slash-skill
            invoked; injected once per turn so the body is not duplicated elsewhere.

    Returns:
        XML envelope string for the plan-context LoopHumanMessage.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    # Build <GOAL_PROGRESS>
    goal_display = _goal_text_for_execute_step_envelope(goal)
    skill_tail = _slash_skill_trailing_user_text(goal_user_submission)
    if skill_tail is not None:
        focus = skill_tail.strip() if skill_tail.strip() else _EMPTY_SKILL_USER_TEXT_PLACEHOLDER
        goal_progress = (
            "<GOAL_PROGRESS>\n"
            "<USER_PRIMARY_QUERY>\n"
            f"{focus}\n"
            "</USER_PRIMARY_QUERY>\n"
            "<FULL_GOAL_AND_SKILL_CONTEXT>\n"
            f"{goal_display}\n"
            "</FULL_GOAL_AND_SKILL_CONTEXT>\n"
            "</GOAL_PROGRESS>"
        )
    else:
        goal_progress = f"<GOAL_PROGRESS>\nGoal: {goal_display}\n</GOAL_PROGRESS>"

    # Optional hints
    extra_parts: list[str] = []
    skill_ref_body = (skill_context or "").strip()
    if skill_ref_body:
        extra_parts.append(f"<SKILL_REFERENCE>\n{skill_ref_body}\n</SKILL_REFERENCE>")
    if step_id_hint:
        extra_parts.append(step_id_hint)
    if dag_context:
        extra_parts.append(dag_context)

    # <CONTEXT_INFO>
    context_info_parts = [
        f"<timestamp>{timestamp}</timestamp>",
        f"<date>{date_str}</date>",
        _RESPONSE_LANGUAGE_HINT,
    ]
    _append_project_instructions_to_context_info(context_info_parts, project_instructions)
    context_info = "<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>"

    parts = [goal_progress] + extra_parts + [context_info]
    return "\n".join(parts)
