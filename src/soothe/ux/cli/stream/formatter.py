"""Formatter functions for CLI display lines."""

from __future__ import annotations

from soothe.foundation.verbosity_tier import VerbosityTier
from soothe.ux.cli.stream.display_line import DisplayLine, indent_for_level


def abbreviate_text(text: str, max_length: int = 50) -> str:
    """Abbreviate text to max_length, preserving start and end.

    Args:
        text: Text to abbreviate.
        max_length: Maximum length before abbreviation.

    Returns:
        Abbreviated text with "..." in middle if too long.

    Examples:
        >>> abbreviate_text("Short text")
        "Short text"
        >>> abbreviate_text("Run cloc on src/ and tests/ directories to count Soothe source and test code")
        "Run cloc on src/ and ... test code"
    """
    if len(text) <= max_length:
        return text

    # Find word boundary in first ~25 chars
    first_end = min(25, len(text))
    while first_end > 0 and text[first_end] != " ":
        first_end -= 1
    if first_end == 0:
        first_end = 25  # No space found, use fixed position

    # Find word boundary in last ~10 chars
    last_start = max(len(text) - 10, 0)
    while last_start < len(text) and text[last_start] != " ":
        last_start += 1
    if last_start == len(text):
        last_start = len(text) - 10  # No space found, use fixed position

    first_part = text[:first_end].rstrip()
    last_part = text[last_start:].lstrip()
    return f"{first_part} ... {last_part}"


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
    # Add inline symbol for goal marker
    content = f"🚩 {goal}"
    return DisplayLine(
        level=1,
        content=content,
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
    # Add inline symbol for step progression
    content = f"⏩ {description}{suffix}"
    return DisplayLine(
        level=2,
        content=content,
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
    # Add inline symbol for tool execution
    content = f"🔧 {name}({args_summary})"
    return DisplayLine(
        level=2,
        content=content,
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
    # Add inline symbol for result status
    inline_symbol = "❌" if is_error else "✨"
    content = f"{inline_symbol} {summary}"
    return DisplayLine(
        level=3,
        content=content,
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
    # Add inline symbol for subagent investigation
    content = f"🕵🏻‍♂️ {brief}"
    return DisplayLine(
        level=3,
        content=content,
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
    # Add inline symbol for subagent investigation complete
    content = f"🕵🏻‍♂️ Done: {summary}"
    return DisplayLine(
        level=3,
        content=content,
        icon="✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_reasoning(
    reasoning: str,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a reasoning line for LLM decision internal analysis.

    IG-XXX: Shows technical reasoning with "Reasoning:" prefix for clarity.

    Args:
        reasoning: Internal technical analysis text.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for reasoning.
    """
    # Polish: Add "Reasoning:" prefix to make internal analysis visible
    content = f"💭 Reasoning: {reasoning}"

    return DisplayLine(
        level=3,  # Use level 3 for less prominence (subordinate to next_action)
        content=content,
        icon="•",
        indent=indent_for_level(3),
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
    content = f"🌀 {judgement}"

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
    # Abbreviate description for cleaner display
    abbreviated = abbreviate_text(description, max_length=50)
    tool_info = f" [{tool_call_count} tools]" if tool_call_count > 0 else ""
    content = f"✅ {abbreviated}{tool_info}"
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
    # Add inline symbol for goal completion celebration
    content = f"🏆 {goal} (complete, {steps} steps)"
    return DisplayLine(
        level=1,
        content=content,
        icon="●",
        indent=indent_for_level(1),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


__all__ = [
    "abbreviate_text",
    "format_goal_done",
    "format_goal_header",
    "format_judgement",
    "format_reasoning",
    "format_step_done",
    "format_step_header",
    "format_subagent_done",
    "format_subagent_milestone",
    "format_tool_call",
    "format_tool_result",
]
