"""User message envelope builder for execute-step (RFC-214).

Builds the XML envelope that wraps per-turn dynamic content:
- <DYNAMIC_CONTEXT>: goal context, execution hints, timestamp
- <RETRIEVED_KNOWLEDGE>: per-turn memories, RAG docs (optional)
- <USER_QUERY>: actual step instruction

This envelope keeps volatile content out of the system prompt,
maximizing prompt cache hits.
"""

from __future__ import annotations

import datetime as dt


def build_execute_step_envelope(
    goal: str | None,
    step_description: str,
    *,
    execution_hints: str | None = None,
    iteration: int | None = None,
    max_iterations: int | None = None,
    workspace_state: str | None = None,
) -> str:
    """Build the user message envelope for an execute-step (RFC-214).

    The envelope contains all per-turn volatile content that should NOT
    be in the system prompt (date, goal context, execution hints).

    Args:
        goal: Current goal text.
        step_description: The step's description (what to execute).
        execution_hints: Optional hints text from ExecutionHintsMiddleware.
        iteration: Current iteration number (1-based for display).
        max_iterations: Maximum iterations allowed.
        workspace_state: Optional lightweight workspace diff summary.

    Returns:
        XML envelope string for the LoopHumanMessage content.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    # Build <DYNAMIC_CONTEXT>
    dynamic_parts: list[str] = []

    # <CURRENT_GOAL>
    goal_text = goal or "No goal specified"
    iter_info = ""
    if iteration is not None and max_iterations is not None:
        iter_info = f" (iteration {iteration}/{max_iterations})"
    dynamic_parts.append(f"<CURRENT_GOAL>\n{goal_text}{iter_info}\n</CURRENT_GOAL>")

    # <EXECUTION_HINTS> (when present)
    if execution_hints:
        dynamic_parts.append(f"<EXECUTION_HINTS>\n{execution_hints}\n</EXECUTION_HINTS>")

    # <CONTEXT_INFO>
    context_info_parts = [
        f"<timestamp>{timestamp}</timestamp>",
        f"<date>{date_str}</date>",
    ]
    if workspace_state:
        context_info_parts.append(f"<workspace_state>{workspace_state}</workspace_state>")
    dynamic_parts.append("<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>")

    dynamic_context = "<DYNAMIC_CONTEXT>\n" + "\n".join(dynamic_parts) + "\n</DYNAMIC_CONTEXT>"

    # <USER_QUERY> - the actual step instruction
    user_query = f"<USER_QUERY>\n{step_description}\n</USER_QUERY>"

    # Assemble full envelope
    return dynamic_context + "\n\n" + user_query


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
        "</CONTEXT_INFO>"
    )

    parts = [goal_progress] + extra_parts + [context_info]
    return "\n".join(parts)
