"""TUI rendering utilities.

This module provides helper functions for creating Rich Text renderables
used by the TUI. Event processing is handled by EventProcessor (RFC-0019).
"""

from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.text import Text

# Claude Code-style dot prefix colors for different event types
# Enhanced palette with semantic categories (Phase 1 of IG-082)
DOT_COLORS: dict[str, str] = {
    # Primary agent activities
    "assistant": "bold blue",
    "assistant_streaming": "cyan",
    "user_input": "bold bright_white",
    # Tool execution lifecycle
    "tool_running": "yellow",
    "tool_success": "green",
    "tool_error": "bold red",
    # Protocol/infrastructure events
    "protocol": "dim white",
    "protocol_highlight": "dim cyan",
    # Subagent namespace colors
    "subagent": "magenta",  # Legacy compatibility
    "subagent_browser": "magenta",
    "subagent_research": "blue_magenta",
    "subagent_claude": "cyan_magenta",
    "subagent_general": "magenta",
    # Cognition/planning events
    "plan_created": "bold cyan",
    "plan_step_active": "yellow",
    "plan_step_done": "green",
    "plan_step_failed": "red",
    # Progress/iteration tracking
    "iteration": "dim yellow",
    "goal": "cyan",
    "progress": "yellow",  # Legacy compatibility
    # Error handling
    "error": "bold red",
    "error_context": "dim red",
    "warning": "yellow",
    "critical": "bold red",
    # Success states
    "success": "bold green",  # Legacy compatibility
    "success_dim": "dim green",
    # Lifecycle events
    "lifecycle": "dim blue",
    "checkpoint": "dim cyan",
}

# Domain-specific icons for instant event recognition (Phase 1 of IG-082)
EVENT_ICONS: dict[str, str] = {
    # Agent activities
    "assistant": "🤖",
    "assistant_streaming": "💬",
    "user_input": ">",
    # Tool execution
    "tool_running": "⚙",
    "tool_success": "✓",
    "tool_error": "✗",
    # Planning/cognition
    "plan_created": "📋",
    "plan_step_active": "◐",
    "plan_step_done": "●",
    "plan_step_failed": "✗",
    "goal": "🎯",
    # Subagent types
    "subagent_browser": "🌐",
    "subagent_research": "📚",
    "subagent_claude": "🧠",
    "subagent_general": "🤖",
    # Protocol/infrastructure
    "protocol": "●",
    "memory": "💾",
    "context": "📄",
    "checkpoint": "📌",
    # Progress tracking
    "iteration": "🔄",
    "progress": "⏳",
    # Status
    "error": "❌",
    "warning": "⚠",
    "success": "✅",
    "critical": "❌",
    # Lifecycle
    "thread_created": "🆕",
    "thread_saved": "💾",
    "thread_resumed": "▶",
}


# Duration formatting constants (in milliseconds)
DURATION_ONE_MINUTE_MS = 60000
DURATION_FIVE_SECONDS_MS = 5000
DURATION_ONE_SECOND_MS = 1000
DURATION_100_MS = 100


def get_icon(category: str, *, unicode_supported: bool = True) -> str:
    """Get icon for category with fallback for non-Unicode terminals.

    Args:
        category: Icon category key (e.g., 'assistant', 'tool_running').
        unicode_supported: Whether terminal supports Unicode emojis.

    Returns:
        Icon string or ASCII fallback.
    """
    if unicode_supported:
        return EVENT_ICONS.get(category, "●")

    # ASCII fallbacks for terminals without Unicode support
    ascii_fallbacks = {
        "assistant": ">",
        "assistant_streaming": ">",
        "tool_running": "*",
        "tool_success": "+",
        "tool_error": "x",
        "plan_created": "#",
        "plan_step_active": "~",
        "plan_step_done": "*",
        "plan_step_failed": "x",
        "subagent_browser": "@",
        "subagent_research": "@",
        "subagent_claude": "@",
        "subagent_general": "@",
        "error": "!",
        "warning": "?",
        "success": "+",
        "critical": "!",
        "iteration": "~",
        "goal": "#",
        "protocol": ".",
        "memory": "M",
        "context": "C",
        "checkpoint": "P",
    }
    return ascii_fallbacks.get(category, "●")


def format_duration_enhanced(duration_ms: int, context: str = "general") -> tuple[str, str]:
    """Format duration with context-aware precision and color.

    Args:
        duration_ms: Duration in milliseconds.
        context: Display context ('general', 'long_running', 'tool', 'plan').

    Returns:
        Tuple of (formatted_string, color_style).
    """
    if duration_ms >= DURATION_ONE_MINUTE_MS:  # >= 1 minute
        seconds = duration_ms / 1000
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        style = "bold dim" if context == "long_running" else "dim"
        return f"{minutes}m {secs}s", style

    if duration_ms >= DURATION_FIVE_SECONDS_MS:  # >= 5 seconds
        return f"{duration_ms / 1000:.1f}s", "bold dim"

    if duration_ms >= DURATION_ONE_SECOND_MS:  # >= 1 second
        return f"{duration_ms / 1000:.2f}s", "dim"

    if duration_ms >= DURATION_100_MS:  # >= 100ms
        return f"{duration_ms}ms", "dim"

    # < 100ms - very fast, show as italic
    return f"{duration_ms}ms", "dim italic"


def make_dot_line(
    color: str,
    text: str | Text,
    body: str | Text | None = None,
    icon: str | None = None,
    *,
    unicode_supported: bool = True,
) -> Text:
    """Create a Claude Code-style line with icon or colored dot prefix.

    Args:
        color: Rich color name for the prefix (e.g., 'blue', 'green', 'red').
        text: Main text to display after the prefix.
        body: Optional body content to show on subsequent lines with tree connector.
        icon: Optional icon category key (uses EVENT_ICONS, e.g., 'assistant', 'tool_running').
        unicode_supported: Whether terminal supports Unicode emojis.

    Returns:
        Rich Text with icon/dot prefix in the given color, followed by the text.
        If body is provided, it's appended on the next line(s) with `  └ ` indent.
    """
    # Use icon if provided, else fallback to standard dot
    prefix_icon = get_icon(icon, unicode_supported=unicode_supported) if icon else "●"
    prefix = Text(prefix_icon + " ", style=color)

    main_text = Text(text) if isinstance(text, str) else text

    result = Text()
    result.append(prefix)
    result.append(main_text)

    if body is not None:
        result.append("\n")
        if isinstance(body, str):
            # Split body into lines and add tree connector to first line
            lines = body.split("\n")
            for i, line in enumerate(lines):
                if i == 0:
                    result.append(Text("  └ ", style="dim"))
                else:
                    result.append(Text("    ", style="dim"))
                result.append(line)
                if i < len(lines) - 1:
                    result.append("\n")
        else:
            result.append(Text("  └ ", style="dim"))
            result.append(body)

    return result


def make_user_prompt_line(text: str) -> Text:
    """Create a user prompt line with heavy right-pointing angle prefix.

    Args:
        text: The user input text to display.

    Returns:
        Rich Text with prompt prefix styled in bold white/bright.
    """
    result = Text()
    result.append("\u276f ", style="bold bright_white")
    result.append(text, style="bold bright_white")
    return result


def make_tool_block(
    name: str,
    args_summary: str,
    output: str | None = None,
    status: str = "running",
    *,
    unicode_supported: bool = True,
) -> Text:
    """Create a Claude Code-style tool block with icon prefix.

    Args:
        name: Tool name to display.
        args_summary: Summary of tool arguments (e.g., "path='/foo'").
        output: Optional tool output to show with tree connector.
        status: Tool status - 'running', 'success', 'error'.
        unicode_supported: Whether terminal supports Unicode emojis.

    Returns:
        Rich Text formatted as:
            ⚙ ToolName(args_summary)
              └ output line 1
                output line 2
    """
    # Determine icon and color based on status
    icon_category = {
        "running": "tool_running",
        "success": "tool_success",
        "error": "tool_error",
    }.get(status, "tool_running")

    color = DOT_COLORS.get(f"tool_{status}", "yellow")

    # Build the tool call line
    tool_text = Text()
    tool_text.append(name, style="bold")
    tool_text.append(f"({args_summary})")

    # Add progress placeholder for running tools
    if status == "running":
        tool_text.append(" ⏳", style="dim yellow")

    return make_dot_line(color, tool_text, output, icon=icon_category, unicode_supported=unicode_supported)


# Minimum segment length when ellipsizing paths (PLR2004).
_MIN_PATH_SEGMENT_LEN = 4

# Left column width for welcome panel key/value rows.
_WELCOME_LABEL_WIDTH = 18
_WELCOME_RULE_WIDTH = 44

# Soothe wordmark (Unicode box drawing) shown on TUI startup.
_WELCOME_LOGO_LINES: tuple[str, ...] = (
    "     ╭────────╮",
    "   ╭╯          ╰╮",
    "  │              │",
    "  │              │",
    "   ╰╮          ╭╯",
    "     ╰───▶────╯",
)


def shorten_display_path(path: str, max_len: int = 76) -> str:
    """Ellipsize a long filesystem path for single-line display.

    Args:
        path: Full path string.
        max_len: Maximum character length before shortening.

    Returns:
        Original path or head + "..." + tail.
    """
    if len(path) <= max_len:
        return path
    head = max_len // 2 - 2
    tail = max_len - head - 3
    if head < _MIN_PATH_SEGMENT_LEN or tail < _MIN_PATH_SEGMENT_LEN:
        return path[: max_len - 3] + "..."
    return path[:head] + "..." + path[-tail:]


def make_welcome_banner(*, workspace: str, provider: str, model_name: str) -> Panel:
    """Build a bordered welcome panel: logo, workspace, provider, and model.

    Args:
        workspace: Current working directory (or client workspace) as a string.
        provider: Resolved LLM provider name (router segment before ``:``).
        model_name: Resolved model id (segment after ``:``), may be empty.

    Returns:
        Rich ``Panel`` suitable for ``ConversationPanel.append_entry``.
    """
    stripped_model = model_name.strip()
    display_model = stripped_model or "(default)"
    ws = shorten_display_path(workspace)
    lw = _WELCOME_LABEL_WIDTH

    inner = Text()
    for line in _WELCOME_LOGO_LINES:
        inner.append(line + "\n", style="dim cyan")
    inner.append("\n")
    inner.append("─" * _WELCOME_RULE_WIDTH + "\n", style="dim")
    inner.append(f"{'Workspace':<{lw}}", style="dim")
    inner.append(ws + "\n", style="bright_white")
    inner.append(f"{'Model provider':<{lw}}", style="dim")
    inner.append(provider + "\n", style="bright_white")
    inner.append(f"{'Model':<{lw}}", style="dim")
    inner.append(display_model + "\n", style="bright_white")

    return Panel(
        inner,
        title=Text("Welcome aboard", style="bold cyan"),
        title_align="center",
        subtitle=Text("Soothe · type a message or /help · ↑↓ for input history", style="dim italic"),
        subtitle_align="center",
        border_style="dim cyan",
        box=box.ROUNDED,
        padding=(0, 1),
        highlight=True,
    )


def make_status_line(text: str, elapsed: str = "") -> Text:
    """Create a status line with asterisk prefix.

    Args:
        text: Status text to display.
        elapsed: Optional elapsed time string to append in parentheses.

    Returns:
        Rich Text formatted as `* {text} ({elapsed})` in yellow/dim style.
    """
    result = Text()
    result.append("* ", style="yellow dim")
    result.append(text, style="yellow dim")
    if elapsed:
        result.append(f" ({elapsed})", style="dim")
    return result
