"""Formatter functions for CLI display lines."""

from __future__ import annotations

from soothe_cli.cli.stream.display_line import DisplayLine, indent_for_level
from soothe_cli.cli.stream.task_scope import (
    format_task_scope_prefix,
    format_task_subagent_line,
)
from soothe_cli.shared.duration_format import format_duration_ms

# Emoji presentation for step-done success (U+2705 + VS16); distinct from ✓ tool rows.
_STEP_DONE_OK_MARK = "\u2705\ufe0f"


def _step_done_tool_suffix(tool_call_count: int) -> str:
    """Parenthetical fragment for tool usage (e.g. `, 4 tools`)."""
    if tool_call_count <= 0:
        return ""
    if tool_call_count == 1:
        return ", 1 tool"
    return f", {tool_call_count} tools"


def format_goal_header(goal: str) -> DisplayLine:
    """Format a goal header line.

    Args:
        goal: Goal description.

    Returns:
        DisplayLine for goal header.
    """
    content = f"📍 {goal}"
    return DisplayLine(
        level=1,
        content=content,
        icon="●",
        indent=indent_for_level(1),
    )


def format_step_header(description: str, *, parallel: bool = False) -> DisplayLine:
    """Format a step header line with checkbox style.

    Args:
        description: Step description.
        parallel: Whether step has parallel tools.

    Returns:
        DisplayLine for step header with hollow circle icon.
    """
    suffix = " (parallel)" if parallel else ""
    content = f"❇️ {description}{suffix}"
    return DisplayLine(
        level=2,
        content=content,
        icon="○",  # Hollow circle for in-progress step
        indent=indent_for_level(2),
    )


def format_subagent_milestone(
    brief: str,
    *,
    task_scope: tuple[str, str] | None = None,
) -> DisplayLine:
    """Format a subagent milestone line showing progress.

    With Task scope: ``⚙ Task(explore):#0 …`` (prefix + brief).

    Args:
        brief: Milestone description (e.g., explore milestone text).
        task_scope: Optional ``(task_tool_call_id, subagent_type)`` for delegated rows.

    Returns:
        DisplayLine for milestone.
    """
    if task_scope:
        tcid, st = task_scope
        content = f"{format_task_scope_prefix(tcid, st)} {brief.strip()}"
        milestone_icon = "⚙"
    else:
        content = brief
        milestone_icon = "●"
    return DisplayLine(
        level=2,
        content=content,
        icon=milestone_icon,
        indent=indent_for_level(2),
    )


def format_subagent_done(
    summary: str,
    duration_s: float,
    *,
    task_scope: tuple[str, str] | None = None,
    task_description: str | None = None,
    task_done_success: bool = True,
    answer_summary: str | None = None,
) -> DisplayLine:
    """Format a subagent completion line with metrics.

    With Task scope: ``⚙ Task(type, \"…\") -> ✓ Completed (human duration)`` using wire task description
    when provided; falls back to summary text inside quotes.
    Without scope: legacy ``✓ …`` row with triple markers.

    Args:
        summary: Metrics fallback when task_description is absent (or failure detail).
        duration_s: Duration in seconds.
        task_scope: Optional ``(task_tool_call_id, subagent_type)`` for delegated rows.
        task_description: Original brief (e.g. explore ``search_target``) when available.
        task_done_success: False for delegated failures (e.g. Claude subagent error).
        answer_summary: Optional one-line answer tail after metrics (IG-344).

    Returns:
        DisplayLine for subagent completion.
    """
    if task_scope:
        tcid, st = task_scope
        desc = (task_description or "").strip() or summary
        quoted = format_task_subagent_line(st, desc)
        ms = max(0, int(duration_s * 1000))
        outcome = "✓ Completed" if task_done_success else "✗ Failed"
        tail = (answer_summary or "").strip()
        base = f"{quoted} -> {outcome} ({format_duration_ms(ms)})"
        content = f"{base}: {tail}" if tail else base
        return DisplayLine(
            level=2,
            content=content,
            icon="⚙",
            indent=indent_for_level(2),
            duration_ms=None,
        )

    duration_ms = int(duration_s * 1000)
    content = f"✓ ✅ ✓ {summary}"
    return DisplayLine(
        level=3,
        content=content,
        icon="✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
    )


def format_plan_phase_reasoning(label: str, text: str) -> DisplayLine:
    """Format a labeled plan-phase reasoning line (assessment vs plan strategy).

    IG-225: Uses level=2 (flat, no indent) for prominent visibility alongside step headers.
    Uses solid bullet ● (matching goal) to indicate reasoning phase is active.

    IG-257: When label is empty, shows text without prefix (just emoji + text).
    """
    if label:
        content = f"💭 {label}: {text}"
    else:
        content = f"💭 {text}"
    return DisplayLine(
        level=2,
        content=content,
        icon="●",  # Solid bullet matching goal icon (polish)
        indent=indent_for_level(2),
    )


def format_judgement(judgement: str, action: str) -> DisplayLine:
    """Format a judgement line for LLM decision reasoning.

    IG-089: Shows meaningful judgement info without raw intermediate data.
    IG-265: Removed [new]/[keep] badge from CLI display (kept in event data for logs).

    Args:
        judgement: Human-readable summary of the decision.
        action: Action taken ("continue" or "complete").

    Returns:
        DisplayLine for judgement.
    """
    action_icon = "○" if action == "continue" else "●"

    content = f"🌟 {judgement}"

    return DisplayLine(
        level=2,
        content=content,
        icon=action_icon,
        indent=indent_for_level(2),
    )


def format_step_done(
    duration_s: float,
    *,
    tool_call_count: int = 0,
    success: bool = True,
    error_msg: str | None = None,
    step_description: str = "",
) -> list[DisplayLine]:
    """Format step completion — same structural pattern as ``format_goal_done`` (IG-333).

    Flat level-1 line: ``● ✅️ {description} (done{, N tools}) (duration)``. If the step
    text is missing on success, returns no lines (no generic ``Step (done)`` placeholder).

    Args:
        duration_s: Duration in seconds.
        tool_call_count: Number of tool calls made during step execution.
        success: Whether step succeeded.
        error_msg: Error message if failed.
        step_description: Human-readable step text (from pipeline context).

    Returns:
        One display line on success when ``step_description`` is non-empty; otherwise an
        empty list on success (avoids a redundant generic ``Step (done)`` line when the
        daemon emits completion without matching step context). On failure, one line
        plus optional error detail line (uses ``Step`` as label only when description is
        missing).
    """
    duration_ms = int(duration_s * 1000)
    tools = _step_done_tool_suffix(tool_call_count)
    desc_stripped = step_description.strip()
    if success and not desc_stripped:
        return []
    desc = desc_stripped or "Step"

    if success:
        content = f"{_STEP_DONE_OK_MARK} {desc} (done{tools})"
        return [
            DisplayLine(
                level=1,
                content=content,
                icon="●",
                indent=indent_for_level(1),
                duration_ms=duration_ms,
            )
        ]

    lines = [
        DisplayLine(
            level=1,
            content=f"✗ {desc} (failed{tools})",
            icon="●",
            indent=indent_for_level(1),
            duration_ms=duration_ms,
        )
    ]
    if error_msg:
        lines.append(
            DisplayLine(
                level=1,
                content=f"Error: {error_msg}",
                icon="",
                indent="",
            )
        )
    return lines


def format_goal_done(goal: str, steps: int, total_s: float) -> DisplayLine:
    """Format a goal completion line.

    Args:
        goal: Goal description.
        steps: Total steps completed.
        total_s: Total duration in seconds.

    Returns:
        DisplayLine for goal done.
    """
    duration_ms = int(total_s * 1000)
    content = f"🏆 {goal} (complete, {steps} steps)"
    return DisplayLine(
        level=1,
        content=content,
        icon="●",
        indent=indent_for_level(1),
        duration_ms=duration_ms,
    )


__all__ = [
    "format_goal_done",
    "format_goal_header",
    "format_judgement",
    "format_plan_phase_reasoning",
    "format_step_done",
    "format_step_header",
    "format_subagent_done",
    "format_subagent_milestone",
]
