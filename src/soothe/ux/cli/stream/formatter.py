"""Formatter functions for CLI display lines."""

from __future__ import annotations

from soothe.core.verbosity_tier import VerbosityTier
from soothe.ux.cli.stream.display_line import DisplayLine, indent_for_level


def _derive_source_prefix(
    namespace: tuple[str, ...],
    verbosity_tier: VerbosityTier,
) -> str | None:
    """Derive source prefix from namespace for debug mode.

    Args:
        namespace: Event namespace tuple (empty = main, non-empty = subagent).
        verbosity_tier: Current verbosity tier.

    Returns:
        Source prefix string if DEBUG level, None otherwise.

    Examples:
        >>> _derive_source_prefix((), VerbosityTier.DEBUG)
        '[main]'
        >>> _derive_source_prefix(('research',), VerbosityTier.DEBUG)
        '[subagent:research]'
        >>> _derive_source_prefix((), VerbosityTier.NORMAL)
        None
    """
    # Only show prefix at DEBUG verbosity
    if verbosity_tier < VerbosityTier.DEBUG:
        return None

    if not namespace:
        return "[main]"
    else:
        # Format: [subagent:name1:name2]
        return "[subagent:" + ":".join(namespace) + "]"


def format_goal_header(
    goal: str,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a goal header line.

    Args:
        goal: Goal description.
        namespace: Event namespace (empty for main, non-empty for subagent).
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for goal header.
    """
    return DisplayLine(
        level=1,
        content=f"Goal: {goal}",
        icon="●",
        indent=indent_for_level(1),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
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
    return DisplayLine(
        level=2,
        content=f"{description}{suffix}",
        icon="○",  # Hollow circle for in-progress step
        indent=indent_for_level(2),
    )


def format_tool_call(name: str, args_summary: str, *, running: bool = False) -> DisplayLine:
    """Format a tool call line.

    Args:
        name: Tool name.
        args_summary: Truncated args.
        running: Whether tool is in parallel mode.

    Returns:
        DisplayLine for tool call.
    """
    return DisplayLine(
        level=2,
        content=f"{name}({args_summary})",
        icon="⚙",
        indent=indent_for_level(2),
        status="running" if running else None,
    )


def format_tool_result(summary: str, duration_ms: int, *, is_error: bool = False) -> DisplayLine:
    """Format a tool result line.

    Args:
        summary: Result summary.
        duration_ms: Duration in milliseconds.
        is_error: Whether result is an error.

    Returns:
        DisplayLine for tool result.
    """
    return DisplayLine(
        level=3,
        content=summary,
        icon="✗" if is_error else "✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
    )


def format_subagent_milestone(brief: str) -> DisplayLine:
    """Format a subagent milestone line.

    Args:
        brief: Milestone description.

    Returns:
        DisplayLine for milestone.
    """
    return DisplayLine(
        level=3,
        content=brief,
        icon="✓",
        indent=indent_for_level(3),
    )


def format_subagent_done(summary: str, duration_s: float) -> DisplayLine:
    """Format a subagent completion line.

    Args:
        summary: Completion summary.
        duration_s: Duration in seconds.

    Returns:
        DisplayLine for subagent done.
    """
    duration_ms = int(duration_s * 1000)
    return DisplayLine(
        level=3,
        content=f"Done: {summary}",
        icon="✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
    )


def format_judgement(judgement: str, action: str) -> DisplayLine:
    """Format a judgement line for LLM decision reasoning.

    IG-089: Shows meaningful judgement info without raw intermediate data.

    Args:
        judgement: Human-readable summary of the decision.
        action: Action taken ("continue" or "complete").

    Returns:
        DisplayLine for judgement.
    """
    action_icon = "→" if action == "continue" else "✓"
    return DisplayLine(
        level=3,
        content=judgement,
        icon=action_icon,
        indent=indent_for_level(3),
    )


def format_step_done(description: str, duration_s: float) -> DisplayLine:
    """Format a step completion line with solid checkbox.

    Args:
        description: Step description (same as header).
        duration_s: Duration in seconds.

    Returns:
        DisplayLine for step done with solid circle icon.
    """
    duration_ms = int(duration_s * 1000)
    return DisplayLine(
        level=2,
        content=description,
        icon="●",  # Solid circle for completed step
        indent=indent_for_level(2),
        duration_ms=duration_ms,
    )


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
    return DisplayLine(
        level=1,
        content=f"Goal: {goal} (complete, {steps} steps)",
        icon="●",
        indent=indent_for_level(1),
        duration_ms=duration_ms,
    )


__all__ = [
    "format_goal_done",
    "format_goal_header",
    "format_judgement",
    "format_step_done",
    "format_step_header",
    "format_subagent_done",
    "format_subagent_milestone",
    "format_tool_call",
    "format_tool_result",
]
