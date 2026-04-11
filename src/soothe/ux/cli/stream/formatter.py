"""Formatter functions for CLI display lines."""

from __future__ import annotations

from soothe.foundation.verbosity_tier import VerbosityTier
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
        >>> _derive_source_prefix(("research",), VerbosityTier.DEBUG)
        '[subagent:research]'
        >>> _derive_source_prefix((), VerbosityTier.NORMAL)
        None
    """
    # Only show prefix at DEBUG verbosity
    if verbosity_tier < VerbosityTier.DEBUG:
        return None

    if not namespace:
        return "[main]"
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
        content=goal,
        icon="●",
        indent=indent_for_level(1),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_step_header(
    description: str,
    *,
    parallel: bool = False,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a step header line with checkbox style.

    Args:
        description: Step description.
        parallel: Whether step has parallel tools.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for step header with hollow circle icon.
    """
    suffix = " (parallel)" if parallel else ""
    return DisplayLine(
        level=2,
        content=f"{description}{suffix}",
        icon="○",  # Hollow circle for in-progress step
        indent=indent_for_level(2),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_tool_call(
    name: str,
    args_summary: str,
    *,
    running: bool = False,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a tool call line.

    Args:
        name: Tool name.
        args_summary: Truncated args.
        running: Whether tool is in parallel mode.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for tool call.
    """
    return DisplayLine(
        level=2,
        content=f"{name}({args_summary})",
        icon="⚙",
        indent=indent_for_level(2),
        status="running" if running else None,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_tool_result(
    summary: str,
    duration_ms: int,
    *,
    is_error: bool = False,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a tool result line.

    Args:
        summary: Result summary.
        duration_ms: Duration in milliseconds.
        is_error: Whether result is an error.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for tool result.
    """
    return DisplayLine(
        level=3,
        content=summary,
        icon="✗" if is_error else "✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_subagent_milestone(
    brief: str,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a subagent milestone line.

    Args:
        brief: Milestone description.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for milestone.
    """
    return DisplayLine(
        level=3,
        content=brief,
        icon="✓",
        indent=indent_for_level(3),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_subagent_done(
    summary: str,
    duration_s: float,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a subagent completion line.

    Args:
        summary: Completion summary.
        duration_s: Duration in seconds.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

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
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_judgement(
    judgement: str,
    action: str,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a judgement line for LLM decision reasoning.

    IG-089: Shows meaningful judgement info without raw intermediate data.
    IG-XXX: Prominent reasoning display with "Reason:" prefix for clarity.

    Args:
        judgement: Human-readable summary of the decision.
        action: Action taken ("continue" or "complete").
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for judgement.
    """
    action_icon = "→" if action == "continue" else "✓"

    # Polish: Add "Reason:" prefix to make LLM reasoning prominent
    content = f"ᦠ {judgement}"

    return DisplayLine(
        level=2,  # Use level 2 for more prominence (like step headers)
        content=content,
        icon=action_icon,
        indent=indent_for_level(2),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_step_done(
    description: str,
    duration_s: float,
    *,
    tool_call_count: int = 0,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a step completion line with solid checkbox.

    Args:
        description: Step description (same as header).
        duration_s: Duration in seconds.
        tool_call_count: Number of tool calls made during step execution.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for step done with solid circle icon.
    """
    duration_ms = int(duration_s * 1000)
    # Add tool call count to content if > 0
    content = f"{description} [{tool_call_count} tools]" if tool_call_count > 0 else description
    return DisplayLine(
        level=2,
        content=content,
        icon="●",  # Solid circle for completed step
        indent=indent_for_level(2),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_goal_done(
    goal: str,
    steps: int,
    total_s: float,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a goal completion line.

    Args:
        goal: Goal description.
        steps: Total steps completed.
        total_s: Total duration in seconds.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for goal done.
    """
    duration_ms = int(total_s * 1000)
    return DisplayLine(
        level=1,
        content=f"{goal} (complete, {steps} steps)",
        icon="●",
        indent=indent_for_level(1),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
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
