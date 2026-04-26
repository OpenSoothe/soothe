"""Formatter functions for CLI display lines."""

from __future__ import annotations

from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.utils import get_tool_display_name

from soothe_cli.cli.stream.display_line import DisplayLine, indent_for_level


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
        >>> abbreviate_text(
        ...     "Run cloc on src/ and tests/ directories to count Soothe source and test code"
        ... )
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
    content = f"{goal}"
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
    content = f"❇️ {description}{suffix}"
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
    """Format a tool/subagent call line.

    IG-256: Restored uniform tool display - no subagent differentiation.
    All tools/subagents use same wrench emoji and gear icon.

    Args:
        name: Tool or subagent name.
        args_summary: Truncated args or query preview.
        running: Whether tool/subagent is running.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for tool/subagent call with uniform wrench icon.
    """
    # Transform to PascalCase for display
    display_name = get_tool_display_name(name)

    # IG-256: No differentiation - use wrench for all tools/subagents
    icon_emoji = "🔧"
    icon_char = "⚙"

    content = f"{icon_emoji} {display_name}({args_summary})"
    return DisplayLine(
        level=2,
        content=content,
        icon=icon_char,
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
        icon="✗" if is_error else "●",  # Solid bullet for success (polish)
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
    """Format a subagent milestone line showing progress.

    IG-256: Restored detective emoji for subagent milestones.

    Args:
        brief: Milestone description (e.g., "Step 3: click on login").
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for milestone with detective emoji.
    """
    # IG-256: Use detective emoji for milestones (restored from IG-255)
    content = f"🕵🏻‍♂️ {brief}"
    return DisplayLine(
        level=3,
        content=content,
        icon="●",  # Solid bullet for milestone (polish)
        indent=indent_for_level(3),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_subagent_done(
    summary: str,
    duration_s: float,
    result_preview: str = "",
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a subagent completion line with metrics.

    IG-256: Restored verbose format with triple success markers and separate result display.
    Result preview parameter is ignored - results show via separate tool events.

    Args:
        summary: Completion summary with subagent-specific metrics (e.g., "success", "$1.23").
        duration_s: Duration in seconds.
        result_preview: Ignored (kept for backward compatibility).
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for subagent done with verbose triple markers.
    """
    duration_ms = int(duration_s * 1000)

    # IG-256: Verbose format restored - triple success markers, result shows separately
    # Format: "✓ ✅ ✓ {summary}"
    # result_preview is ignored - let result show via separate tool execution events
    content = f"✓ ✅ ✓ {summary}"

    return DisplayLine(
        level=3,
        content=content,
        icon="✓",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_plan_phase_reasoning(
    label: str,
    text: str,
    *,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a labeled plan-phase reasoning line (assessment vs plan strategy).

    IG-225: Uses level=2 (flat, no indent) for prominent visibility alongside step headers.
    Uses solid bullet ● (matching goal) to indicate reasoning phase is active.

    IG-257: When label is empty, shows text without prefix (just emoji + text).
    """
    # IG-257: Handle empty label (no prefix)
    if label:
        content = f"💭 {label}: {text}"
    else:
        content = f"💭 {text}"
    return DisplayLine(
        level=2,
        content=content,
        icon="●",  # Solid bullet matching goal icon (polish)
        indent=indent_for_level(2),
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
    Uses solid bullet ● (matching goal) to indicate reasoning is active phase.

    IG-262: Uses level=2 (flat layout) for consistency with judgement lines.
    Reasoning is a sibling to judgement, not a child.

    Args:
        reasoning: Internal technical analysis text.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for reasoning.
    """
    # Polish: Add "Reasoning:" prefix to make internal analysis visible
    content = f"💭 {reasoning}"

    return DisplayLine(
        level=2,  # IG-262: Use level 2 for flat layout (sibling to judgement, not child)
        content=content,
        icon="●",  # Solid bullet matching goal icon (polish)
        indent=indent_for_level(2),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_judgement(
    judgement: str,
    action: str,
    *,
    plan_action: str | None = None,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> DisplayLine:
    """Format a judgement line for LLM decision reasoning.

    IG-089: Shows meaningful judgement info without raw intermediate data.
    IG-XXX: Prominent reasoning display with "Reason:" prefix for clarity.
    IG-265: Removed [new]/[keep] badge from CLI display (kept in event data for logs).

    Args:
        judgement: Human-readable summary of the decision.
        action: Action taken ("continue" or "complete").
        plan_action: Ignored (kept for backward compatibility, appears in logs only).
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for judgement.
    """
    action_icon = "○" if action == "continue" else "●"  # Polish: ○ for continue, ● for complete

    # IG-265: Remove badge from CLI display (plan_action kept in event data for logs)
    content = f"🌟 {judgement}"

    return DisplayLine(
        level=2,  # Use level 2 for more prominence (like step headers)
        content=content,
        icon=action_icon,
        indent=indent_for_level(2),
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    )


def format_step_done(
    duration_s: float,
    *,
    tool_call_count: int = 0,
    success: bool = True,
    error_msg: str | None = None,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> list[DisplayLine]:
    """Format step completion as level-3 child node (IG-182).

    IG-159/IG-182: Shows brief "Done"/"Failed" with tree connector as child of step header.
    No description repeat - user already saw it in the step header above.

    IG-257: Uses Unicode tree branch "└─" (U+2514) for cleaner visual tree.

    Args:
        duration_s: Duration in seconds.
        tool_call_count: Number of tool calls made during step execution.
        success: Whether step succeeded.
        error_msg: Error message if failed.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        List of DisplayLine objects for step result tree (1-2 lines).
    """
    duration_ms = int(duration_s * 1000)
    tool_info = f" [{tool_call_count} tools]" if tool_call_count > 0 else ""

    # Success case: single line
    if success:
        content = f"✓ Done{tool_info}"
        return [
            DisplayLine(
                level=3,  # Child node of step header (level 2)
                content=content,
                icon="└─",  # IG-257: Unicode tree branch (U+2514)
                indent=indent_for_level(3),
                duration_ms=duration_ms,
                source_prefix=_derive_source_prefix(namespace, verbosity_tier),
            )
        ]

    # Error case: result line + optional error detail
    lines = [
        DisplayLine(
            level=3,
            content=f"✗ Failed{tool_info}",
            icon="└─",  # IG-257: Unicode tree branch (U+2514)
            indent=indent_for_level(3),
            duration_ms=duration_ms,
            source_prefix=_derive_source_prefix(namespace, verbosity_tier),
        )
    ]

    # Show error message on level-4 line if present
    if error_msg:
        lines.append(
            DisplayLine(
                level=4,  # Error detail as child of failed result
                content=f"Error: {error_msg}",
                icon="└─",  # IG-257: Unicode tree branch (U+2514)
                indent=indent_for_level(4),
                source_prefix=_derive_source_prefix(namespace, verbosity_tier),
            )
        )

    return lines


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
    "format_plan_phase_reasoning",
    "format_reasoning",
    "format_step_done",
    "format_step_header",
    "format_subagent_done",
    "format_subagent_milestone",
    "format_tool_call",
    "format_tool_result",
]
