"""Message widgets for Soothe."""

from __future__ import annotations

import logging
import os
import re
import weakref
from dataclasses import dataclass
from time import monotonic, time
from typing import TYPE_CHECKING, Any

from soothe_sdk.utils import get_tool_display_name
from soothe_sdk.ux.task_namespace import (
    is_step_level_task_tool_id,
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
)
from textual import on
from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.reactive import var
from textual.widgets import Static

from soothe_cli.runtime.parse.message_processing import _normalize_tool_name_for_arg_map
from soothe_cli.runtime.presentation.duration_format import format_duration, format_duration_ms
from soothe_cli.tui import theme
from soothe_cli.tui._env_vars import TUI_REFRESH_INTERVAL_MS
from soothe_cli.tui.commands.subagent_routing import get_subagent_display_name
from soothe_cli.tui.config import (
    MODE_DISPLAY_GLYPHS,
    PREFIX_TO_MODE,
    get_glyphs,
    is_ascii_mode,
)
from soothe_cli.tui.input import EMAIL_PREFIX_PATTERN, INPUT_HIGHLIGHT_PATTERN
from soothe_cli.tui.preview_limits import (
    APPROVAL_DIFF_MAX_LINES,
    SKILL_CARD_PREVIEW_CHARS,
    SKILL_CARD_PREVIEW_LINES,
    STEP_CARD_SHOW_TOOL_ROW_DETAILS,
    STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD,
)
from soothe_cli.tui.widgets._links import open_style_link
from soothe_cli.tui.widgets.clipboard import (
    clear_widget_text_selection,
    screen_has_text_selection,
)
from soothe_cli.tui.widgets.diff import compose_diff_lines

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer
    from textual.widgets import Markdown
    from textual.widgets._markdown import MarkdownStream

logger = logging.getLogger(__name__)


def _click_has_text_selection(widget: Static | Vertical) -> bool:
    """Return True when the screen still has an active text selection."""
    return screen_has_text_selection(widget.screen)


_STEP_TOOL_PREVIEW_ROWS = STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD
"""Collapsed step/task activity preview shows this many rows (IG-402)."""

_MAX_STEP_STAT_TOOL_KINDS = 4
_MAX_TASK_DELEGATION_DESC_CHARS = 80
"""Max distinct tool display names in the running-line stats suffix before ``+N more``."""

# IG-420: TUI refresh throttling - minimum interval between widget refreshes
_DEFAULT_TUI_REFRESH_INTERVAL_MS = 800
"""Default minimum interval between TUI refreshes in milliseconds."""

_global_refresh_interval_ms: int | None = None


def _get_tui_refresh_interval_ms() -> int:
    """Get the TUI refresh interval from environment or default.

    Returns:
        Minimum interval between refreshes in milliseconds.
    """
    global _global_refresh_interval_ms
    if _global_refresh_interval_ms is not None:
        return _global_refresh_interval_ms
    env_val = os.environ.get(TUI_REFRESH_INTERVAL_MS)
    if env_val:
        try:
            parsed = int(env_val.strip())
            if parsed >= 50:  # Minimum 50ms to prevent UI lockup
                _global_refresh_interval_ms = parsed
                return parsed
        except ValueError:
            pass
    _global_refresh_interval_ms = _DEFAULT_TUI_REFRESH_INTERVAL_MS
    return _DEFAULT_TUI_REFRESH_INTERVAL_MS


def _should_refresh_now(last_refresh_time: float | None) -> bool:
    """Check if enough time has passed since last refresh for throttling.

    Args:
        last_refresh_time: Monotonic time of last refresh, or None if never refreshed.

    Returns:
        True if refresh should proceed, False if throttled.
    """
    if last_refresh_time is None:
        return True
    interval_secs = _get_tui_refresh_interval_ms() / 1000.0
    return (monotonic() - last_refresh_time) >= interval_secs


_RUNNING_SPINNER_INTERVAL_SECONDS = 0.2
"""Spinner/status animation cadence for running cards."""

_RUNNING_ROWS_REFRESH_INTERVAL_SECONDS = 0.5
"""Minimum interval between expensive running-row re-renders."""

# Deferred tool-list refresh (turn-level coalescing + global repaint budget).
_DEFERRED_TOOL_REFRESH_WIDGETS: weakref.WeakSet[Any] = weakref.WeakSet()
_global_tools_list_refresh_at: float = 0.0


def reset_turn_tool_refresh_state() -> None:
    """Clear deferred refresh registry at the start of a new agent turn."""
    global _global_tools_list_refresh_at
    _global_tools_list_refresh_at = 0.0
    _DEFERRED_TOOL_REFRESH_WIDGETS.clear()


def request_deferred_tools_refresh(widget: Any) -> None:
    """Queue a card for batched tool-list repaint."""
    _DEFERRED_TOOL_REFRESH_WIDGETS.add(widget)


def flush_deferred_tools_refreshes(*, force: bool = False) -> None:
    """Repaint queued tool cards (global budget unless ``force``)."""
    global _global_tools_list_refresh_at
    pending = list(_DEFERRED_TOOL_REFRESH_WIDGETS)
    if not pending:
        return
    now = monotonic()
    if not force:
        interval = _get_tui_refresh_interval_ms() / 1000.0
        if now - _global_tools_list_refresh_at < interval:
            return
    _global_tools_list_refresh_at = now
    _DEFERRED_TOOL_REFRESH_WIDGETS.clear()
    for widget in pending:
        flush_fn = getattr(widget, "_flush_deferred_tools_refresh", None)
        if callable(flush_fn):
            flush_fn()


def _tui_hint_expand_body(ellipsis_glyph: str) -> str:
    """Whole card or section is folded; user can open it."""
    return ""


def _tui_hint_collapse_body(ellipsis_glyph: str) -> str:
    """Whole card or section is open; user can fold it."""
    return ""


def _tui_hint_expand_plain() -> str:
    """Expand hint without a leading ellipsis (rare short-truncation paths)."""
    return ""


def _tui_hint_expand_lines(ellipsis_glyph: str, remaining: int) -> str:
    """Preview truncated by line count."""
    return ""


def _tui_hint_expand_more_text(ellipsis_glyph: str) -> str:
    """Preview truncated primarily by character budget."""
    return ""


def _tui_hint_expand_truncation(ellipsis_glyph: str, truncation: str) -> str:
    """Tool/output preview with formatter-supplied tail (e.g. ``3 more lines``)."""
    return ""


def _tui_hint_expand_more_tool_calls(ellipsis_glyph: str, remaining: int) -> str:
    """Step/task tool list preview."""
    return ""


def _is_widget_animation_visible(widget: object) -> bool:
    """Return whether a widget is currently visible on screen.

    This is used to skip animation work for off-screen cards.
    """
    try:
        if not getattr(widget, "is_attached", False):
            return False
        if not getattr(widget, "visible", True):
            return False
        is_on_screen = getattr(widget, "is_on_screen", True)
        if callable(is_on_screen):
            return bool(is_on_screen())
        return bool(is_on_screen)
    except Exception:
        return False


def _assemble_card_header(widget: object, label_part: str, body_part: str) -> Content:
    """Build a card title: cognition-colored label plus foreground body (no bold).

    Used for Goal, Plan, Step, and tool (including Task) headers so hierarchy
    comes from color, not weight. Body uses ``foreground`` so titles stay
    readable on dark backgrounds (parity with step tool rows).

    Args:
        widget: Mounted widget (or any object accepted by ``get_theme_colors``).
        label_part: Left segment (e.g. ``⎿ 📍 ``).
        body_part: Right segment (goal text, args, etc.).

    Returns:
        Assembled ``Content`` for a ``Static`` header.
    """
    try:
        colors = theme.get_theme_colors(widget)
    except Exception:  # noqa: BLE001
        colors = theme.DARK_COLORS
    return Content.assemble(
        Content.styled(label_part, colors.cognition),
        Content.styled(body_part, colors.foreground),
    )


def _show_timestamp_toast(widget: Static | Vertical) -> None:
    """Show a toast with the message's creation timestamp.

    No-ops silently if the widget is not mounted or has no associated message
    data in the store.

    Args:
        widget: The message widget whose timestamp to display.
    """
    from datetime import UTC, datetime

    try:
        app = widget.app
    except Exception:  # noqa: BLE001  # Textual raises when widget has no app
        return
    if not widget.id:
        return
    store = app._message_store  # type: ignore[attr-defined]
    data = store.get_message(widget.id)
    if not data:
        return
    dt = datetime.fromtimestamp(data.timestamp, tz=UTC).astimezone()
    label = f"{dt:%b} {dt.day}, {dt.hour % 12 or 12}:{dt:%M:%S} {dt:%p}"
    app.notify(label, timeout=3)


class _TimestampClickMixin:
    """Mixin that shows a timestamp toast on click.

    Add to any message widget that should display its creation timestamp when
    clicked. Widgets needing additional click behavior (e.g. `ToolCallMessage`,
    `AppMessage`) should override `on_click` and call `_show_timestamp_toast`
    directly instead.
    """

    def on_click(self, event: Click) -> None:  # noqa: ARG002  # Textual event handler
        """Show timestamp toast on click."""
        if _click_has_text_selection(self):  # type: ignore[arg-type]
            return
        _show_timestamp_toast(self)  # type: ignore[arg-type]


def _mode_color(mode: str | None, widget_or_app: object | None = None) -> str:
    """Return the hex color string for a mode, falling back to primary.

    Args:
        mode: Mode name (e.g. `'shell'`, `'command'`) or `None`.
        widget_or_app: Textual widget or `App` for theme-aware lookup.

    Returns:
        Color string from the active theme's `ThemeColors`.
    """
    colors = theme.get_theme_colors(widget_or_app)
    if not mode:
        return colors.primary
    if mode == "shell":
        return colors.mode_bash
    if mode == "command":
        return colors.mode_command
    logger.warning("Missing color for mode '%s'; falling back to primary.", mode)
    return colors.primary


@dataclass(frozen=True, slots=True)
class FormattedOutput:
    """Result of formatting tool output for display."""

    content: Content
    """Styled `Content` for the formatted output."""

    truncation: str | None = None
    """Description of truncated content (e.g., "10 more lines"), or None if no
    truncation occurred."""


_SUCCESS_EXIT_RE = re.compile(r"\n?\[Command succeeded with exit code 0\]\s*$")
"""Strip the SDK's `[Command succeeded with exit code 0]` trailer from tool output."""


def _strip_success_exit_line(text: str) -> str:
    """Remove the `[Command succeeded with exit code 0]` trailer.

    Non-zero exit codes are left intact (they come through `set_error`).

    Args:
        text: Raw tool output string.

    Returns:
        Text with the success exit-code trailer removed, if present.
    """
    return _SUCCESS_EXIT_RE.sub("", text)


class UserMessage(_TimestampClickMixin, Static):
    """Widget displaying a user message with enhanced styling."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0;
        background: transparent;
        border-left: wide $primary;
    }

    UserMessage.-mode-shell {
        border-left: wide $mode-bash;
    }

    UserMessage.-mode-command {
        border-left: wide $mode-command;
    }

    UserMessage:hover {
        opacity: 0.9;
    }
    """
    """Consistent styling with transparent background and colored borders matching other cards."""

    def __init__(self, content: str, **kwargs: Any) -> None:
        """Initialize a user message.

        Args:
            content: The message content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content

    def on_mount(self) -> None:
        """Add CSS classes for mode-specific border and ASCII border type."""
        mode = PREFIX_TO_MODE.get(self._content[:1]) if self._content else None
        if mode:
            self.add_class(f"-mode-{mode}")
        if is_ascii_mode():
            self.add_class("-ascii")

    def render(self) -> Content:
        """Render the styled user message with role indicator.

        Returns:
            Styled Content with role header, mode prefix, and highlighted mentions.
        """
        colors = theme.get_theme_colors(self)
        parts: list[str | tuple[str, str]] = []
        content = self._content

        # Add role indicator header
        parts.append(("> ", f"bold {colors.primary}"))

        # Use mode-specific prefix indicator when content starts with a
        # mode trigger character (e.g. "!" for shell, "/" for commands).
        # The display glyph may differ from the trigger (e.g. "$" for shell).
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            parts.append((f"{glyph} ", f"bold {_mode_color(mode, self)}"))
            content = content[1:]

        # Highlight @mentions and /commands in the content
        last_end = 0
        for match in INPUT_HIGHLIGHT_PATTERN.finditer(content):
            start, end = match.span()
            token = match.group()

            # Skip @mentions that look like email addresses
            if token.startswith("@") and start > 0:
                char_before = content[start - 1]
                if EMAIL_PREFIX_PATTERN.match(char_before):
                    continue

            # Add text before the match (unstyled)
            if start > last_end:
                parts.append(content[last_end:start])

            # The regex only matches tokens starting with / or @
            if token.startswith("/") and start == 0:
                # /command at start
                parts.append((token, f"bold {colors.warning}"))
            elif token.startswith("@"):
                # @file mention
                parts.append((token, f"bold {colors.primary}"))
            last_end = end

        # Add remaining text after last match
        if last_end < len(content):
            parts.append(content[last_end:])

        return Content.assemble(*parts)


class QueuedUserMessage(Static):
    """Widget displaying a queued (pending) user message in grey.

    This is an ephemeral widget that gets removed when the message is dequeued.
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    QueuedUserMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $panel;
        opacity: 0.6;
    }
    """
    """Dimmed border + reduced opacity to distinguish queued messages from sent ones."""

    def __init__(self, content: str, **kwargs: Any) -> None:
        """Initialize a queued user message.

        Args:
            content: The message content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content

    def on_mount(self) -> None:
        """Add ASCII border class when in ASCII mode."""
        if is_ascii_mode():
            self.add_class("-ascii")

    def render(self) -> Content:
        """Render the queued user message (greyed out).

        Returns:
            Styled Content with dimmed prefix and body.
        """
        colors = theme.get_theme_colors(self)
        content = self._content
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            prefix = (f"{glyph} ", f"bold {colors.muted}")
            content = content[1:]
        else:
            prefix = ("> ", f"bold {colors.muted}")
        return Content.assemble(prefix, (content, colors.muted))


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter delimited by `---` markers.

    Args:
        text: Raw `SKILL.md` content.

    Returns:
        Body text with frontmatter removed and leading whitespace stripped.
    """
    from soothe_cli.tui.skills.load import strip_skill_frontmatter

    return strip_skill_frontmatter(text)


class _SkillToggle(Static):
    """Clickable header/hint area for toggling skill body expansion.

    Referenced by name in `SkillMessage._on_toggle_click`'s `@on(Click)`
    CSS selector — rename with care.
    """


class SkillMessage(Vertical):
    """Widget displaying a skill invocation with collapsible body.

    Shows skill name, source badge, description, and user args as a compact
    header. The full SKILL.md body (frontmatter stripped) is hidden behind a
    preview/expand toggle (click or Ctrl+O).  The expanded view renders
    markdown via Rich's `Markdown` inside a single `Static` widget.

    Visibility is driven by a CSS class (`-expanded`) toggled via a Textual
    reactive `var`. Click handlers are scoped to the header and hint widgets
    (`_SkillToggle`) so clicks on the rendered markdown body do not trigger
    expansion toggles (preserving text selection, for instance).
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    SkillMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $skill;
    }

    SkillMessage .skill-header {
        height: auto;
    }

    SkillMessage .skill-description {
        color: $text-muted;
        margin-left: 3;
    }

    SkillMessage .skill-args {
        margin-left: 3;
        margin-top: 0;
    }

    SkillMessage #skill-md {
        margin-left: 3;
        margin-top: 0;
        padding: 0;
        display: none;
    }

    SkillMessage .skill-hint {
        margin-left: 3;
        color: $text-muted;
        background: transparent;
    }

    SkillMessage.-expanded #skill-md {
        display: block;
    }

    SkillMessage:hover {
        border-left: wide $skill-hover;
    }
    """

    _PREVIEW_LINES = SKILL_CARD_PREVIEW_LINES
    _PREVIEW_CHARS = SKILL_CARD_PREVIEW_CHARS

    _expanded: var[bool] = var(False, toggle_class="-expanded")

    def __init__(
        self,
        skill_name: str,
        description: str = "",
        source: str = "",
        body: str = "",
        args: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a skill message.

        Args:
            skill_name: Skill identifier.
            description: Short description of the skill.
            source: Origin label (e.g., `'built-in'`, `'user'`).
            body: Full SKILL.md content (frontmatter included).
            args: User-provided arguments.
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
        self._skill_name = skill_name
        self._description = description
        self._source = source
        self._body = body
        self._stripped_body = _strip_frontmatter(body)
        self._args = args
        self._md_widget: Static | None = None
        self._hint_widget: _SkillToggle | None = None
        self._deferred_expanded: bool = False
        self._md_rendered: bool = False

    def compose(self) -> ComposeResult:
        """Compose the skill message layout.

        Yields:
            Widgets for header, description, args, and collapsible body.
        """
        colors = theme.get_theme_colors()
        source_tag = f" [{self._source}]" if self._source else ""
        yield _SkillToggle(
            Content.styled(
                f"/ skill:{self._skill_name}{source_tag}",
                f"bold {colors.skill}",
            ),
            classes="skill-header",
        )
        if self._description:
            yield _SkillToggle(
                Content.styled(self._description, "dim"),
                classes="skill-description",
            )
        if self._args:
            yield Static(
                Content.assemble(
                    ("User request: ", "bold"),
                    self._args,
                ),
                classes="skill-args",
            )
        yield Static("", id="skill-md")
        yield _SkillToggle("", classes="skill-hint", id="skill-hint")

    def on_mount(self) -> None:
        """Cache widget references, render initial state.

        Ordering matters: widget refs must be cached before `_prepare_body`
        or `_deferred_expanded` assignment, because either may set
        `_expanded` which fires `watch__expanded` synchronously.
        """
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border_left = ("ascii", colors.skill)

        self._md_widget = self.query_one("#skill-md", Static)
        self._hint_widget = self.query_one("#skill-hint", _SkillToggle)

        body = self._stripped_body.strip()
        if body:
            self._prepare_body(body)

        if self._deferred_expanded:
            self._expanded = self._deferred_expanded
            self._deferred_expanded = False

    def _prepare_body(self, body: str) -> None:
        """Set initial hint text. Full body render is deferred to first expand.

        Args:
            body: Stripped markdown body text.
        """
        lines = body.split("\n")
        total_lines = len(lines)
        needs_truncation = total_lines > self._PREVIEW_LINES or len(body) > self._PREVIEW_CHARS

        if needs_truncation:
            remaining = total_lines - self._PREVIEW_LINES
            ellipsis = get_glyphs().ellipsis
            if self._hint_widget:
                self._hint_widget.update(
                    Content.styled(
                        _tui_hint_expand_lines(ellipsis, remaining),
                        "dim",
                    )
                )
        else:
            # Short body — show fully rendered, no preview needed.
            self._ensure_md_rendered(body)
            self._expanded = True

    def _ensure_md_rendered(self, body: str) -> None:
        """Render markdown into the Static widget on first call, then no-op.

        Args:
            body: Stripped markdown body text.
        """
        if self._md_rendered or not self._md_widget:
            return
        try:
            from rich.markdown import Markdown as RichMarkdown

            self._md_widget.update(RichMarkdown(body))
        except Exception:
            logger.warning(
                "Failed to render skill body as markdown; falling back to plain text",
                exc_info=True,
            )
            self._md_widget.update(body)
        self._md_rendered = True

    def toggle_body(self) -> None:
        """Toggle between preview and full body display."""
        if not self._stripped_body.strip():
            return
        self._expanded = not self._expanded

    def watch__expanded(self, expanded: bool) -> None:
        """Lazy-render markdown on first expand; update hint text."""
        body = self._stripped_body.strip()
        if not body:
            return

        if expanded:
            self._ensure_md_rendered(body)

        if not self._hint_widget:
            return

        lines = body.split("\n")
        total_lines = len(lines)
        needs_truncation = total_lines > self._PREVIEW_LINES or len(body) > self._PREVIEW_CHARS

        if not needs_truncation:
            # Short body — always fully visible, no hint needed.
            self._hint_widget.display = False
            return

        if expanded:
            self._hint_widget.update(
                Content.styled(_tui_hint_collapse_body(get_glyphs().ellipsis), "dim italic")
            )
        else:
            remaining = total_lines - self._PREVIEW_LINES
            ellipsis = get_glyphs().ellipsis
            self._hint_widget.update(
                Content.styled(
                    _tui_hint_expand_lines(ellipsis, remaining),
                    "dim",
                )
            )

    @on(Click, "_SkillToggle")
    def _on_toggle_click(self, event: Click) -> None:
        """Toggle expansion when header or hint is clicked."""
        event.stop()
        if self._stripped_body.strip():
            self.toggle_body()
        else:
            _show_timestamp_toast(self)


class AssistantMessage(Vertical):
    """Assistant reply card: markdown or plain text body (no title row).

    When ``render_markdown`` is enabled (default), model output is rendered as
    Markdown. When disabled, output is shown verbatim. User and assistant messages
    are always shown in full (no truncation or collapse).
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
    }

    AssistantMessage Markdown {
        padding: 0;
        margin: 0;
        height: auto;
    }

    AssistantMessage .assistant-body {
        padding: 0;
        margin: 0;
        height: auto;
    }

    AssistantMessage:hover {
        opacity: 0.95;
    }
    """

    # Performance optimization: batch streaming updates to reduce render frequency
    _STREAM_FLUSH_INTERVAL: float = 0.05  # 50ms batching for streaming

    def __init__(self, content: str = "", **kwargs: Any) -> None:
        """Initialize an assistant message.

        Args:
            content: Initial assistant text (rendered as Markdown if enabled).
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
        self._content = content
        self._markdown: Markdown | None = None
        self._body: Static | None = None
        self._stream: MarkdownStream | None = None
        self._streaming_active: bool = False

        # Batching buffer for streaming content
        self._pending_buffer: str = ""
        self._flush_timer: Timer | None = None

        # Determine markdown rendering from config
        self._render_markdown: bool = True
        try:
            from soothe_cli.config.loader import load_config

            config = load_config()
            self._render_markdown = config.render_markdown
        except Exception:
            pass  # Default to True if config unavailable

    def compose(self) -> ComposeResult:  # noqa: PLR6301  # Textual widget method convention
        """Compose markdown body or plain body."""
        if self._render_markdown:
            from textual.widgets import Markdown

            yield Markdown("", id="assistant-md")
        else:
            yield Static("", markup=False, classes="assistant-body", id="assistant-body")

    def on_mount(self) -> None:
        """Wire child widgets."""
        if is_ascii_mode():
            self.add_class("-ascii")

        if self._render_markdown:
            from textual.widgets import Markdown

            self._markdown = self.query_one("#assistant-md", Markdown)
        else:
            self._body = self.query_one("#assistant-body", Static)

    def _get_markdown(self) -> Markdown:
        """Return the markdown widget, querying if not cached."""
        if self._markdown is None:
            from textual.widgets import Markdown

            self._markdown = self.query_one("#assistant-md", Markdown)
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream:
        """Ensure the markdown stream is initialized."""
        if self._stream is None:
            from textual.widgets import Markdown

            self._stream = Markdown.get_stream(self._get_markdown())
        return self._stream

    def on_click(self, event: Click) -> None:
        """Show timestamp toast on click."""
        event.stop()
        if _click_has_text_selection(self):
            return
        _show_timestamp_toast(self)

    async def _flush_pending_content(self) -> None:
        """Flush buffered content to stream or body widget (batched update)."""
        self._flush_timer = None
        if not self._pending_buffer:
            return

        text = self._pending_buffer
        self._pending_buffer = ""

        if self._render_markdown:
            stream = self._ensure_stream()
            await stream.write(text)
        elif self._body is not None:
            await self._body.update(self._content)

    async def append_content(self, text: str) -> None:
        """Append content to the message (for streaming with batching).

        Uses internal buffering to batch writes and reduce render frequency.
        """
        if not text:
            return

        # Accumulate content
        self._content += text
        self._pending_buffer += text
        self._streaming_active = True

        # Schedule batched flush if not already scheduled
        if self._flush_timer is None:
            self._flush_timer = self.set_timer(
                self._STREAM_FLUSH_INTERVAL,
                self._flush_pending_content,
            )

    async def write_initial_content(self) -> None:
        """Write initial content from constructor and finalize streaming state."""
        if self._content:
            self._streaming_active = True
            if self._render_markdown:
                stream = self._ensure_stream()
                await stream.write(self._content)
            elif self._body is not None:
                await self._body.update(self._content)
            await self.stop_stream()

    async def stop_stream(self) -> None:
        """End streaming batched updates."""
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None

        if self._pending_buffer:
            await self._flush_pending_content()

        self._streaming_active = False
        if self._render_markdown:
            stream_was_active = self._stream is not None
            if self._stream is not None:
                await self._stream.stop()
                self._stream = None
            # Textual's incremental `Markdown.append` (used by MarkdownStream) can
            # leave fenced code blocks / merged tails inconsistent once the stream
            # ends. Re-parse the full document so the finished card matches what a
            # one-shot render would produce.
            if stream_was_active and self._content:
                try:
                    await self._get_markdown().update(self._content)
                except Exception:
                    logger.debug(
                        "AssistantMessage: full markdown refresh after stream failed",
                        exc_info=True,
                    )
        elif self._body is not None:
            await self._body.update(self._content)

    async def set_content(self, content: str) -> None:
        """Set the full message content (stops any active stream)."""
        await self.stop_stream()
        self._content = content
        self._pending_buffer = ""
        if self._render_markdown and self._markdown:
            await self._markdown.update(content)
        elif self._body:
            await self._body.update(content)


class DiffMessage(_TimestampClickMixin, Static):
    """Widget displaying a diff with syntax highlighting."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    DiffMessage {
        height: auto;
        padding: 1;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $primary;
    }

    DiffMessage .diff-header {
        text-style: bold;
        margin-bottom: 1;
    }

    DiffMessage .diff-add {
        color: $text-success;
        background: $success-muted;
    }

    DiffMessage .diff-remove {
        color: $text-error;
        background: $error-muted;
    }

    DiffMessage .diff-context {
        color: $text-muted;
    }

    DiffMessage .diff-hunk {
        color: $secondary;
        text-style: bold;
    }
    """
    """Diff syntax coloring per theme: additions, removals, muted context."""

    def __init__(
        self,
        diff_content: str,
        file_path: str = "",
        *,
        action_label: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a diff message.

        Args:
            diff_content: The unified diff content
            file_path: Path to the file being modified
            action_label: Short verb for the change (e.g. ``Updated``, ``Deleted``)
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._diff_content = diff_content
        self._file_path = file_path
        self._action_label = action_label.strip()

    def compose(self) -> ComposeResult:
        """Compose the diff message layout.

        Yields:
            Widgets displaying the diff header and formatted content.
        """
        if self._file_path:
            if self._action_label:
                yield Static(
                    Content.from_markup(
                        "[bold]$action:[/bold] $path",
                        action=self._action_label,
                        path=self._file_path,
                    ),
                    classes="diff-header",
                )
            else:
                yield Static(
                    Content.from_markup("[bold]File: $path[/bold]", path=self._file_path),
                    classes="diff-header",
                )

        # Render the diff with per-line Statics (CSS-driven backgrounds)
        yield from compose_diff_lines(self._diff_content, max_lines=APPROVAL_DIFF_MAX_LINES)

    def on_mount(self) -> None:
        """Set border style based on charset mode."""
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)


@dataclass
class _StepToolRow:
    """One tool invocation row on the step card (IG-402, IG-419).

    IG-419: Supports nesting via parent_tool_call_id for inner subagent tools.
    Task delegation rows (is_task_row=True) are parent headers; inner tools
    nest underneath with indentation.
    """

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    phase: str  # pending | running | success | error | rejected | skipped
    output: str = ""
    duration_ms: int = 0
    started_at: float | None = None
    parent_tool_call_id: str | None = None  # IG-419: Link to parent task row for nesting
    is_task_row: bool = False  # IG-419: Mark as task delegation parent row


class CognitionStepMessage(Vertical):
    """Agent-loop act step card: aggregates main-agent tool calls (IG-402).

    Header is the step description only. Task delegations render in a branch panel
    (``Name(desc)`` plus nested tool lines with phase). Per-tool-kind counts of direct
    main-agent tools appear on the footer status line via :meth:`_stats_title_suffix`
    (e.g. ``Glob(10)``). The status line is always the last body line (running,
    pending, completed, failed). Individual CLI-style tool rows are optional
    (``STEP_CARD_SHOW_TOOL_ROW_DETAILS``). When tool rows are enabled and exceed
    ``_STEP_TOOL_PREVIEW_ROWS``, click first folds or unfolds the tool list; otherwise
    click toggles whole-card collapse. Subagent notes and execute prose can
    auto-collapse the card body until the user expands it (a new ``set_running`` clears
    that preference).

    Tool rows use the goal-tree gutter (``⎿``) plus hollow/filled circles when shown.
    Prose / notes keep ``⎿ ○`` continuation lines.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionStepMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionStepMessage .step-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionStepMessage .step-status {
        margin-left: 0;
    }

    CognitionStepMessage .step-status.pending {
        color: $cognition;
    }

    CognitionStepMessage .step-status.queued {
        color: $cognition;
    }

    CognitionStepMessage .step-tools {
        margin-left: 0;
        margin-top: 0;
        height: auto;
        color: $text-muted;
    }

    CognitionStepMessage .step-subagent-notes {
        margin-left: 0;
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-detail {
        margin-left: 0;
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-collapse-hint {
        margin-left: 0;
        color: $text-muted;
        background: transparent;
        height: auto;
    }

    CognitionStepMessage.-collapsed .step-tools,
    CognitionStepMessage.-collapsed .step-status,
    CognitionStepMessage.-collapsed .step-subagent-notes,
    CognitionStepMessage.-collapsed .step-detail {
        display: none;
    }

    CognitionStepMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    def __init__(
        self,
        step_id: str,
        description: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._step_id = step_id
        self._description = description.strip()
        self._status = "pending"  # pending | queued | running | success | error
        self._spinner_position = 0
        self._start_time: float | None = None
        self._animation_timer: Timer | None = None
        self._last_rows_animation_refresh: float = 0.0
        # IG-420: Throttling for refresh methods
        self._last_tools_refresh: float | None = None
        self._last_header_refresh: float | None = None
        self._tools_refresh_pending = False
        self._row_cache_key_by_id: dict[str, tuple[Any, ...]] = {}
        self._row_content_by_id: dict[str, Content] = {}
        self._tools_panel_cache_key: tuple[Any, ...] | None = None
        self._status_widget: Static | None = None
        self._header_widget: Static | None = None
        self._tools_widget: Static | None = None
        self._detail_widget: Static | None = None
        self._deferred_complete: tuple[bool, int, int, str] | None = None
        self._deferred_running: bool = False
        self._last_success: bool | None = None
        self._last_duration_ms: int = 0
        self._last_tool_call_count: int = 0
        self._last_summary: str = ""
        self._interrupt_message: str | None = None
        self._deferred_interrupted: str | None = None
        self._rows: list[_StepToolRow] = []
        self._row_index: dict[str, _StepToolRow] = {}
        self._stats_order: list[str] = []
        self._stats_counts: dict[str, int] = {}
        self._tools_body_collapsed: bool = False
        self._subagent_notes: list[str] = []
        self._subagent_notes_by_task: dict[str, list[str]] = {}
        self._task_activity_start_times: dict[str, float] = {}
        """Per task-delegation key: monotonic time when subgraph activity began."""
        self._execute_assistant_buffer: str = ""
        self._last_completed_execute_prose: str = ""
        """Execute-step prose frozen when ``set_complete`` runs (TUI dedupe vs goal_completion)."""
        self._card_collapsed: bool = False
        """Whether the entire card body is collapsed (header remains visible)."""
        self._collapse_hint_widget: Static | None = None
        """Widget showing expand/collapse hint text."""
        self._step_card_user_expanded: bool = False
        """If True, skip auto-collapse (user expanded the card body)."""
        self._step_tool_list_user_expanded: bool = False
        """If True, skip auto-folding the tool-row preview (user expanded the list)."""

    def _step_body_line_estimate(self) -> int:
        """Approximate expanded-body line count for auto-collapse."""
        n = len(self._subagent_notes)
        for notes in self._subagent_notes_by_task.values():
            n += len(notes)
        for task_row in self._iter_task_delegation_rows():
            n += 1
            child_rows = self._child_rows_for_task(task_row)
            if child_rows:
                n += 1
                if self._effective_task_delegation_phase(task_row, child_rows) == "running":
                    n += 1
            elif self._status in ("pending", "queued"):
                n += 1
            n += len(self._subagent_notes_by_task.get(str(task_row.tool_call_id).strip(), []))
        if self._status in ("pending", "queued") and not self._iter_task_delegation_rows():
            n += 1
        if STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            n += len(self._rows)
        buf = (self._execute_assistant_buffer or "").strip()
        if buf:
            n += len(buf.splitlines())
        elif (self._last_completed_execute_prose or "").strip():
            n += len(self._last_completed_execute_prose.splitlines())
        if self._status in ("success", "error"):
            n += 1
        elif self._status == "running":
            n += 1
        return n

    def _maybe_auto_fold_step_tool_list(self) -> None:
        """Fold long tool lists to the preview cap while the step runs (not only after complete)."""
        if not STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            return
        if self._step_tool_list_user_expanded:
            return
        if len(self._rows) <= _STEP_TOOL_PREVIEW_ROWS:
            return
        if self._tools_body_collapsed:
            return
        self._tools_body_collapsed = True

    def _maybe_auto_collapse_step_card(self) -> None:
        if self._step_card_user_expanded:
            return
        if self._step_body_line_estimate() <= STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD:
            return
        if self._card_collapsed:
            return
        self._card_collapsed = True
        self._refresh_collapse_state()

    @property
    def last_completed_execute_prose(self) -> str:
        """Prose accumulated from ``execute_step`` for this step when it completed."""
        return self._last_completed_execute_prose

    def set_description(self, description: str) -> None:
        """Update the step title (full plan/execute brief, no abbreviation)."""
        text = (description or "").strip() or "(step)"
        if text == self._description:
            return
        self._description = text
        self._refresh_header_title()

    def _step_header_content(self) -> Content:
        return _assemble_card_header(
            self,
            "🚀 ",
            self._description,
        )

    def compose(self) -> ComposeResult:
        yield Static(
            self._step_header_content(),
            classes="step-header",
            id="step-cognition-header",
        )
        yield Static("", classes="step-tools", id="step-cognition-tools", markup=False)
        yield Static(
            "",
            markup=False,
            classes="step-subagent-notes",
            id="step-cognition-subagent-notes",
        )
        yield Static("", classes="step-detail", id="step-cognition-detail")
        yield Static("", classes="step-status", id="step-cognition-status")
        yield Static("", classes="step-collapse-hint", id="step-collapse-hint")

    def on_mount(self) -> None:
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
        self._header_widget = self.query_one("#step-cognition-header", Static)
        self._status_widget = self.query_one("#step-cognition-status", Static)
        self._tools_widget = self.query_one("#step-cognition-tools", Static)
        self._detail_widget = self.query_one("#step-cognition-detail", Static)
        self._collapse_hint_widget = self.query_one("#step-collapse-hint", Static)
        notes = self.query_one("#step-cognition-subagent-notes", Static)
        notes.display = False
        self._status_widget.display = False
        self._tools_widget.display = False
        self._detail_widget.display = False
        self._collapse_hint_widget.display = False
        self._refresh_header_title()
        self._refresh_tools_display()
        self._refresh_collapse_state()
        if self._execute_assistant_buffer.strip() and self._status == "running":
            self._refresh_execute_assistant_running_display()
        if self._deferred_interrupted is not None:
            msg = self._deferred_interrupted
            self._deferred_interrupted = None
            self.set_interrupted(msg)
        elif self._deferred_complete is not None:
            success, duration_ms, tool_call_count, summary = self._deferred_complete
            self._deferred_complete = None
            self.set_complete(success, duration_ms, tool_call_count, summary)
        elif self._deferred_running:
            self._deferred_running = False
            self.set_running()
        elif self._status == "queued":
            self._refresh_queued_display()
        elif self._status == "pending":
            self._refresh_pending_display()

        self._maybe_auto_collapse_step_card()

    def on_click(self, event: Click) -> None:  # noqa: ARG002
        """Toggle tool-row folding, card collapse, or show timestamp."""
        event.stop()
        if _click_has_text_selection(self):
            return
        if (
            STEP_CARD_SHOW_TOOL_ROW_DETAILS
            and self._rows
            and len(self._rows) > _STEP_TOOL_PREVIEW_ROWS
        ):
            was_collapsed = self._tools_body_collapsed
            self._tools_body_collapsed = not self._tools_body_collapsed
            if was_collapsed and not self._tools_body_collapsed:
                self._step_tool_list_user_expanded = True
            self._refresh_tools_display()
            return
        has_collapsible_content = (
            (STEP_CARD_SHOW_TOOL_ROW_DETAILS and self._rows)
            or self._has_task_activity_body()
            or self._execute_assistant_buffer.strip()
            or self._status in ("success", "error")
        )
        if has_collapsible_content:
            self.toggle_collapse()
        else:
            _show_timestamp_toast(self)

    def toggle_collapse(self) -> None:
        """Toggle the entire card body collapse state."""
        was_collapsed = self._card_collapsed
        self._card_collapsed = not self._card_collapsed
        if was_collapsed and not self._card_collapsed:
            self._step_card_user_expanded = True
        self._refresh_collapse_state()

    def _refresh_collapse_state(self) -> None:
        """Update CSS classes and footer hint based on collapse state."""
        if self._card_collapsed:
            self.add_class("-collapsed")
        else:
            self.remove_class("-collapsed")
        self._sync_step_footer_hint()

    def _sync_step_footer_hint(self) -> None:
        """Single footer line after status: expand card or tool-list affordances.

        Note: The expand/collapse icon is now shown inline in the status line,
        so this widget is hidden for a cleaner design.
        """
        w = self._collapse_hint_widget
        if w is None:
            return
        # Hide the separate hint widget - icon is shown inline in status line
        w.display = False
        # Refresh status line to update the inline expand/collapse icon
        if self._status == "running":
            self._update_running_animation()
        elif self._status in ("success", "error") and self._detail_widget:
            # Re-apply completion detail with updated icon
            dur_str = format_duration_ms(self._last_duration_ms)
            tool_part = self._status_tool_stats_suffix(self._last_tool_call_count)
            if self._last_success:
                status_body = f"Completed ({dur_str}){tool_part}"
                self._update_step_footer_status_line(
                    status_body,
                    success=True,
                )
                prose = (self._last_completed_execute_prose or "").strip()
                if prose and self._detail_widget:
                    self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                    self._detail_widget.display = True
                elif self._detail_widget:
                    self._detail_widget.display = False
            else:
                err_text = self._last_summary.strip() or "Step failed"
                self._update_step_footer_status_line(
                    f"Failed · {dur_str}",
                    success=False,
                )
                self._detail_widget.update(self._step_branched_error_detail(err_text))

    def append_execute_assistant_delta(self, delta: str) -> None:
        """Accumulate per-step LoopAIMessage (``phase=execute_step``) prose into this card."""
        if not delta:
            return
        self._execute_assistant_buffer += delta
        if self._status == "running":
            self._refresh_execute_assistant_running_display()
        self._maybe_auto_collapse_step_card()

    def _refresh_execute_assistant_running_display(self) -> None:
        body = self._execute_assistant_buffer.strip()
        if not body or self._detail_widget is None:
            return
        self._detail_widget.update(self._step_branched_execute_body(body, muted=True))
        self._detail_widget.display = True

    def _has_task_activity_body(self) -> bool:
        """True when the step card should show the task-activity tree panel."""
        if self._subagent_notes or self._subagent_notes_by_task:
            return True
        if self._status in ("pending", "queued"):
            return True
        return bool(self._iter_task_delegation_rows())

    def _task_delegation_dedupe_key(self, row: _StepToolRow) -> str:
        """Stable key for one main-graph task delegation (aliases share one branch)."""
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return ""
        if row.is_task_row or is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                return tcid
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return tcid

    @staticmethod
    def _prefer_task_delegation_row(candidate: _StepToolRow, incumbent: _StepToolRow) -> bool:
        """True when ``candidate`` should replace ``incumbent`` for the same task key."""
        if candidate.is_task_row and not incumbent.is_task_row:
            return True
        if incumbent.is_task_row and not candidate.is_task_row:
            return False
        return len(candidate.args or {}) >= len(incumbent.args or {})

    def _iter_task_delegation_rows(self) -> list[_StepToolRow]:
        """Task delegation rows on this step (unified ``{step}:s:task:…`` ids)."""
        by_key: dict[str, _StepToolRow] = {}
        for row in self._rows:
            if not row.is_task_row and not is_step_level_task_tool_id(row.tool_call_id):
                continue
            # Skip rows that belong to OTHER steps (parsed step_id != this card's step_id).
            parsed_sid, _, _, _ = parse_unified_tool_call_id(str(row.tool_call_id or ""))
            if parsed_sid and parsed_sid != self._step_id:
                continue
            key = self._task_delegation_dedupe_key(row)
            if not key:
                continue
            prev = by_key.get(key)
            if prev is None or self._prefer_task_delegation_row(row, prev):
                by_key[key] = row
        return sorted(by_key.values(), key=lambda r: r.tool_call_id)

    def _task_idx_from_delegation_row(self, task_row: _StepToolRow) -> int | None:
        """Task index encoded in a step-level ``task`` unified id (``task:0`` → 0)."""
        _, type_code, _, tool_info = parse_unified_tool_call_id(task_row.tool_call_id)
        if type_code != "s":
            return None
        head = (tool_info or "").split(":")[0]
        if head != "task":
            return None
        tail = (tool_info or "").split(":")[-1]
        if tail.isdigit():
            return int(tail)
        return 0

    def _task_parent_ids_match(self, parent_id: str, row_parent_id: str) -> bool:
        """True when two tool_call_ids refer to the same step-level task delegation."""
        if not row_parent_id:
            return False
        if row_parent_id == parent_id:
            return True
        if is_step_level_task_tool_id(parent_id) or is_step_level_task_tool_id(row_parent_id):
            p_sid, _, _, _ = parse_unified_tool_call_id(parent_id)
            r_sid, _, _, _ = parse_unified_tool_call_id(row_parent_id)
            if p_sid != self._step_id or r_sid != self._step_id:
                return parent_id == row_parent_id
            return normalize_step_task_tool_call_id(
                self._step_id, row_parent_id
            ) == normalize_step_task_tool_call_id(self._step_id, parent_id)
        return False

    def _child_rows_for_task(self, task_row: _StepToolRow) -> list[_StepToolRow]:
        """Subgraph tool rows for one task (``parent_tool_call_id`` or ``{step}:t{n}:…``)."""
        raw_parent = str(task_row.tool_call_id).strip()
        parsed_sid, _, _, _ = parse_unified_tool_call_id(raw_parent)
        if parsed_sid and parsed_sid == self._step_id:
            parent_id = normalize_step_task_tool_call_id(self._step_id, raw_parent)
        else:
            parent_id = raw_parent
        task_idx = self._task_idx_from_delegation_row(task_row)
        by_id: dict[str, _StepToolRow] = {}
        for row in self._rows:
            if row.is_task_row or is_step_level_task_tool_id(row.tool_call_id):
                continue
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            row_parent = str(row.parent_tool_call_id or "").strip()
            if self._task_parent_ids_match(parent_id, row_parent):
                by_id[tcid] = row
                continue
            if task_idx is not None:
                sid, type_code, idx, _ = parse_unified_tool_call_id(tcid)
                if (
                    sid == self._step_id
                    and type_code == "t"
                    and idx is not None
                    and idx == task_idx
                ):
                    by_id[tcid] = row
        return sorted(by_id.values(), key=lambda r: r.tool_call_id)

    def _task_delegation_label(self, task_row: _StepToolRow) -> str:
        """Display label ``SubAgentName(description)`` for a task delegation row."""
        args = dict(task_row.args or {})
        raw_type = args.get("subagent_type", "")
        if isinstance(raw_type, str):
            st = raw_type.strip()
        else:
            st = str(raw_type or "").strip()
        name = get_subagent_display_name(st) if st else "Task"
        desc = args.get("description") or args.get("prompt") or ""
        if isinstance(desc, str):
            desc_text = desc.strip()
        else:
            desc_text = str(desc or "").strip()
        if len(desc_text) > _MAX_TASK_DELEGATION_DESC_CHARS:
            desc_text = desc_text[: _MAX_TASK_DELEGATION_DESC_CHARS - 3].rstrip() + "..."
        if desc_text:
            return f"{name}({desc_text})"
        return name

    def _phase_icon(self, phase: str, g: Any, *, animate_running: bool = False) -> str:
        """Lifecycle glyph for a task branch or tool row."""
        p = (phase or "pending").strip().lower()
        if p in ("success", "done"):
            return g.checkmark
        if p in ("error", "rejected", "failed"):
            return g.error
        if p == "running" and animate_running:
            frames = g.spinner_frames
            return frames[self._spinner_position % len(frames)]
        return g.circle_empty

    def _task_tool_phase_icon(self, row: _StepToolRow, g: Any) -> str:
        """Glyph for a task-branch tool row from its lifecycle phase."""
        return self._phase_icon(row.phase or "pending", g)

    def _task_tool_status_tail(self, row: _StepToolRow) -> str:
        """Trailing status text for a task-branch tool row (duration, failure, etc.)."""
        phase = (row.phase or "pending").strip().lower()
        if phase == "success" and row.duration_ms > 0:
            return f" ({format_duration_ms(row.duration_ms)})"
        if phase == "error":
            return " · failed"
        if phase == "rejected":
            return " · rejected"
        if phase == "skipped":
            return " · skipped"
        if phase == "running":
            return " · running"
        return ""

    def _task_tool_row_tone(self, row: _StepToolRow, colors: Any) -> str:
        return self._task_tool_row_tone_for_phase(row.phase or "pending", colors)

    def _task_tool_row_tone_for_phase(self, phase: str, colors: Any) -> str:
        p = (phase or "pending").strip().lower()
        if p in ("success", "done"):
            return colors.cognition
        if p in ("error", "rejected", "failed"):
            return colors.error
        if p == "running":
            return colors.cognition
        return colors.muted

    def _task_children_aggregate_phase(self, rows: list[_StepToolRow]) -> str:
        """Aggregate lifecycle phase for nested tools under one task delegation."""
        if not rows:
            return "pending"
        phases = {(r.phase or "pending").strip().lower() for r in rows}
        if "running" in phases:
            return "running"
        if "error" in phases or "rejected" in phases:
            return "failed"
        if phases <= {"success"}:
            return "success"
        if phases <= {"skipped"}:
            return "skipped"
        if "pending" in phases:
            return "pending"
        return "pending"

    def _task_children_aggregate_status(self, rows: list[_StepToolRow]) -> str:
        """Status suffix for nested tools under one task (running / failed / done)."""
        phase = self._task_children_aggregate_phase(rows)
        if phase == "running":
            return " · running"
        if phase == "failed":
            return " · failed"
        if phase == "success":
            return " · done"
        if phase == "skipped":
            return " · skipped"
        if phase == "pending":
            return " · pending"
        return ""

    def _effective_task_delegation_phase(
        self,
        task_row: _StepToolRow,
        child_rows: list[_StepToolRow],
    ) -> str:
        """Derived phase for a task delegation from its subgraph tool rows."""
        if child_rows:
            return self._task_children_aggregate_phase(child_rows)
        return (task_row.phase or "pending").strip().lower()

    def _touch_task_activity_start(self, task_key: str) -> None:
        """Record when subgraph activity began for elapsed-time display."""
        key = str(task_key or "").strip()
        if key and key not in self._task_activity_start_times:
            self._task_activity_start_times[key] = time()

    def _task_delegation_elapsed_suffix(self, task_key: str) -> str:
        start = self._task_activity_start_times.get(str(task_key or "").strip())
        if start is None:
            return ""
        elapsed_secs = int(time() - start)
        return f" ({format_duration(float(elapsed_secs))})"

    def _has_active_task_branch_animation(self) -> bool:
        """True when any task delegation branch needs live spinner/elapsed updates."""
        for task_row in self._iter_task_delegation_rows():
            child_rows = self._child_rows_for_task(task_row)
            if self._effective_task_delegation_phase(task_row, child_rows) == "running":
                return True
        return False

    def _task_children_stats_tone(self, phase: str, colors: Any) -> str:
        p = (phase or "pending").strip().lower()
        if p == "running":
            return colors.cognition
        if p in ("failed", "error", "rejected"):
            return colors.error
        if p == "success":
            return colors.cognition
        return colors.muted

    def _update_step_footer_status_line(self, status_line_body: str, *, success: bool) -> None:
        """Paint the step card footer status (always the last visible body line)."""
        if self._status_widget is None:
            return
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        icon = g.checkmark if success else g.error
        tone = colors.cognition if success else colors.error
        has_collapsible = (
            (STEP_CARD_SHOW_TOOL_ROW_DETAILS and self._rows)
            or self._has_task_activity_body()
            or bool((self._last_completed_execute_prose or "").strip())
            or bool((self._execute_assistant_buffer or "").strip())
        )
        collapse_icon = (
            f" {g.expand if self._card_collapsed else g.collapse}" if has_collapsible else ""
        )
        self._status_widget.remove_class("pending")
        self._status_widget.update(
            Content.styled(
                f"{gutter}{icon} {status_line_body}{collapse_icon}",
                tone,
            )
        )
        self._status_widget.display = True

    def _tool_stats_suffix_for_rows(self, rows: list[_StepToolRow]) -> str:
        """Per-tool-kind counts for a set of tool rows (e.g. nested task children).

        Sorted by call count descending (most calls first). Shows ``+N more`` for
        additional tool kinds beyond the display limit.
        """
        ids_by_display: dict[str, set[str]] = {}
        for row in rows:
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            display = get_tool_display_name(_normalize_tool_name_for_arg_map(row.tool_name or ""))
            if display not in ids_by_display:
                ids_by_display[display] = set()
            ids_by_display[display].add(tcid)
        if not ids_by_display:
            return ""
        # Sort by count descending (most calls first)
        sorted_kinds = sorted(
            ids_by_display.keys(), key=lambda k: len(ids_by_display[k]), reverse=True
        )
        parts: list[str] = []
        for name in sorted_kinds[:_MAX_STEP_STAT_TOOL_KINDS]:
            parts.append(f"{name}({len(ids_by_display[name])})")
        text = ", ".join(parts)
        extra = len(sorted_kinds) - _MAX_STEP_STAT_TOOL_KINDS
        if extra > 0:
            text += f" +{extra} more"
        return text

    def _normalized_task_note_key(self, task_tool_call_id: str) -> str:
        tcid = str(task_tool_call_id).strip()
        if not tcid:
            return ""
        if is_step_level_task_tool_id(tcid):
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return tcid

    def _step_task_activity_content(self) -> Content:
        """Task delegations under the step title: ``Name(desc)`` and child tool stats."""
        g = get_glyphs()
        branch_gutter = f"{g.output_prefix} "
        child_gutter = f"{g.output_prefix}   "
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        parts: list[object] = []
        first_block = True

        task_rows = self._iter_task_delegation_rows()
        if not task_rows and self._status in ("pending", "queued"):
            status_word = "Queued..." if self._status == "queued" else "Pending..."
            return Content.styled(
                f"{branch_gutter}{g.circle_empty} {status_word}",
                colors.muted,
            )

        for task_row in task_rows:
            if not first_block:
                parts.append("\n")
            first_block = False
            task_key = self._task_delegation_dedupe_key(task_row)
            child_rows = self._child_rows_for_task(task_row)
            eff_phase = self._effective_task_delegation_phase(task_row, child_rows)
            if eff_phase == "running" and task_key:
                self._touch_task_activity_start(task_key)

            task_icon = self._phase_icon(eff_phase, g, animate_running=False)
            label = self._task_delegation_label(task_row)
            task_tone = self._task_tool_row_tone_for_phase(eff_phase, colors)
            parts.append(
                Content.styled(
                    f"{branch_gutter}{task_icon} {label}",
                    task_tone if eff_phase != "pending" else colors.foreground,
                )
            )

            if child_rows:
                child_stats = self._tool_stats_suffix_for_rows(child_rows)
                if child_stats:
                    child_status = self._task_children_aggregate_status(child_rows)
                    parts.append("\n")
                    parts.append(
                        Content.styled(
                            f"{child_gutter}{child_stats}{child_status}",
                            self._task_children_stats_tone(eff_phase, colors),
                        )
                    )
                if eff_phase == "running":
                    elapsed = self._task_delegation_elapsed_suffix(task_key)
                    toggle = ""
                    if self._card_collapsed:
                        toggle = f" {g.expand}"
                    elif self._has_task_activity_body():
                        toggle = f" {g.collapse}"
                    frame = self._phase_icon("running", g, animate_running=True)
                    parts.append("\n")
                    parts.append(
                        Content.styled(
                            f"{child_gutter}{frame} Running...{elapsed}{toggle}",
                            colors.cognition,
                        )
                    )
            elif self._status in ("pending", "queued"):
                wait_word = "Queued..." if self._status == "queued" else "Pending..."
                parts.append("\n")
                parts.append(
                    Content.styled(
                        f"{child_gutter}{g.circle_empty} {wait_word}",
                        colors.muted,
                    )
                )

            for note in self._subagent_notes_by_task.get(task_key, []):
                text = (note or "").strip()
                if not text:
                    continue
                parts.append("\n")
                parts.append(Content.styled(f"{child_gutter}{text}", colors.muted))

        for note in self._subagent_notes:
            t = (note or "").strip()
            if not t:
                continue
            if not first_block:
                parts.append("\n")
            first_block = False
            parts.append(Content.styled(f"{branch_gutter}{t}", colors.muted))

        return Content.assemble(*parts) if parts else Content("")

    def _refresh_task_activity_display(self) -> None:
        """Repaint the task-activity tree under the step header."""
        show = self._has_task_activity_body()
        try:
            w = self.query_one("#step-cognition-subagent-notes", Static)
        except Exception:  # noqa: BLE001
            if show:
                self._maybe_auto_collapse_step_card()
            return
        if show:
            w.update(self._step_task_activity_content())
            w.display = True
        else:
            w.display = False
        self._maybe_auto_collapse_step_card()

    def append_subagent_activity(
        self,
        line: str,
        *,
        task_tool_call_id: str | None = None,
    ) -> None:
        """Append prose or metadata for a delegated task (optional unified parent id)."""
        text = (line or "").strip()
        if not text:
            return
        task_key = self._normalized_task_note_key(task_tool_call_id or "")
        if task_key:
            self._subagent_notes_by_task.setdefault(task_key, []).append(text)
        else:
            self._subagent_notes.append(text)
        self._refresh_task_activity_display()

    def _row_belongs_to_step(self, row: _StepToolRow) -> bool:
        """True when ``row`` belongs to this step card (unified id encodes step)."""
        parsed_sid, _, _, _ = parse_unified_tool_call_id(row.tool_call_id)
        if parsed_sid:
            return parsed_sid == self._step_id
        return True

    def _row_counts_for_step_status_line(self, row: _StepToolRow) -> bool:
        """True for main-agent tools on this step (excludes task rows and nested subgraph tools)."""
        if row.is_task_row or row.parent_tool_call_id:
            return False
        if not self._row_belongs_to_step(row):
            return False
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return False
        if is_step_level_task_tool_id(tcid):
            return False
        _, type_code, _, _ = parse_unified_tool_call_id(tcid)
        if type_code == "t":
            return False
        return True

    def _rebuild_tool_stats(self) -> None:
        """Recompute per-tool display counts for the step status line (direct tools only).

        Sorted by count descending (most calls first).
        """
        ids_by_display: dict[str, set[str]] = {}
        for row in self._rows:
            if not self._row_counts_for_step_status_line(row):
                continue
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            display = get_tool_display_name(_normalize_tool_name_for_arg_map(row.tool_name or ""))
            if display not in ids_by_display:
                ids_by_display[display] = set()
            ids_by_display[display].add(tcid)
        # Sort by count descending (most calls first)
        self._stats_order = sorted(
            ids_by_display.keys(), key=lambda k: len(ids_by_display[k]), reverse=True
        )
        self._stats_counts = {name: len(ids_by_display[name]) for name in self._stats_order}
        self._refresh_task_activity_display()

    def _stats_title_suffix(self) -> str:
        if not self._stats_order:
            return ""
        parts: list[str] = []
        for name in self._stats_order[:_MAX_STEP_STAT_TOOL_KINDS]:
            parts.append(f"{name}({self._stats_counts.get(name, 0)})")
        text = ", ".join(parts)
        extra = len(self._stats_order) - _MAX_STEP_STAT_TOOL_KINDS
        if extra > 0:
            text += f" +{extra} more"
        return f" · {text}"

    def _status_tool_stats_suffix(self, fallback_count: int = 0) -> str:
        """Per-tool breakdown for status lines; total-only when rows were not tracked."""
        suffix = self._stats_title_suffix()
        if suffix:
            return suffix
        if fallback_count > 0:
            return f" · {fallback_count} tools"
        return ""

    def _refresh_header_title(self) -> None:
        if self._header_widget is None:
            return
        self._header_widget.update(self._step_header_content())

    def _step_goal_tree_gutter(self) -> str:
        """Left column matching :meth:`CognitionGoalTreeMessage._indent_prefix`."""
        return f"{get_glyphs().output_prefix} "

    def _row_to_content(self, row: _StepToolRow) -> Content:
        """Tool rows are not rendered in the TUI (stats-only tracking)."""
        del row
        return Content("")

    def _step_branched_execute_body(self, body: str, *, muted: bool = True) -> Content:
        """Streamed execute-phase prose: tree gutter per line."""
        g = get_glyphs()
        gutter = f"{g.output_prefix} {g.circle_empty} "
        text = (body or "").rstrip()
        if not text:
            return Content("")
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        style = colors.muted if muted else colors.success
        parts: list[object] = []
        for i, ln in enumerate(text.splitlines()):
            if i:
                parts.append("\n")
            parts.append(Content.styled(f"{gutter}{ln}", style))
        return Content.assemble(*parts)

    def _step_branched_completion_detail(
        self,
        *,
        success: bool,
        status_line_body: str,
        prose: str,
    ) -> Content:
        """Completed step detail: first line ``⎿ ✓|✗ status``; prose lines ``⎿ ○ …``."""
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        icon = g.checkmark if success else g.error
        # Match running step line and tool activity: cognition accent, not semantic green.
        tone = colors.cognition if success else colors.error
        # Add expand/collapse icon at the end of status line
        collapse_icon = g.expand if self._card_collapsed else g.collapse
        parts: list[object] = [
            Content.styled(f"{gutter}{icon} {status_line_body} {collapse_icon}", tone),
        ]
        prose = (prose or "").strip()
        if prose:
            sub = f"{g.output_prefix} {g.circle_empty} "
            prose_style = colors.muted if success else tone
            parts.append("\n")
            for i, ln in enumerate(prose.splitlines()):
                if i:
                    parts.append("\n")
                parts.append(Content.styled(f"{sub}{ln}", prose_style))
        return Content.assemble(*parts)

    def _step_branched_error_detail(self, err_text: str) -> Content:
        """Multiline error body: first line ``⎿ ✗ …``; continuations ``⎿ ○ …``."""
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        raw = (err_text or "").strip()
        if not raw:
            return Content("")
        lines = raw.splitlines()
        parts: list[object] = []
        for i, ln in enumerate(lines):
            if i:
                parts.append("\n")
            if i == 0:
                parts.append(Content.styled(f"{gutter}{g.error} {ln}", colors.error))
            else:
                sub = f"{g.output_prefix} {g.circle_empty} "
                parts.append(Content.styled(f"{sub}{ln}", colors.error))
        return Content.assemble(*parts)

    def _build_nested_row_order(self) -> list[_StepToolRow]:
        """Build ordered list: task rows followed by their nested children (IG-419).

        Inner subagent tools (with parent_tool_call_id) appear indented under
        their parent task delegation row. Non-task, non-child rows appear at end.
        """
        task_rows = [r for r in self._rows if r.is_task_row]
        child_by_parent: dict[str, list[_StepToolRow]] = {}
        other_rows: list[_StepToolRow] = []

        for r in self._rows:
            if r.is_task_row:
                continue
            if r.parent_tool_call_id:
                child_by_parent.setdefault(r.parent_tool_call_id, []).append(r)
            else:
                other_rows.append(r)

        result: list[_StepToolRow] = []
        for task_row in task_rows:
            result.append(task_row)
            children = child_by_parent.get(task_row.tool_call_id, [])
            # Sort children by tool_call_id to maintain order
            children.sort(key=lambda x: x.tool_call_id)
            result.extend(children)

        # Append remaining non-task rows at the end
        result.extend(other_rows)
        return result

    def request_tools_display_refresh(self, *, immediate: bool = False) -> None:
        """Queue or run a tool-list repaint (batched across cards during streaming)."""
        if immediate:
            self._tools_refresh_pending = False
            self._refresh_tools_display(force=True)
            return
        self._tools_refresh_pending = True
        request_deferred_tools_refresh(self)

    def _flush_deferred_tools_refresh(self) -> None:
        if not self._tools_refresh_pending:
            return
        self._tools_refresh_pending = False
        self._refresh_tools_display(force=False)

    def _row_content_cache_key(self, row: _StepToolRow) -> tuple[Any, ...]:
        args_key: tuple[tuple[str, Any], ...] = ()
        if row.args:
            try:
                args_key = tuple(sorted((str(k), v) for k, v in row.args.items()))
            except TypeError:
                args_key = (repr(row.args),)
        return (
            row.tool_call_id,
            row.phase,
            row.tool_name,
            row.duration_ms,
            row.output,
            args_key,
            row.parent_tool_call_id,
            row.is_task_row,
        )

    def _refresh_tools_display(self, *, force: bool = False) -> None:
        # IG-420: When widget not mounted, always run auto-collapse checks (no throttling)
        if self._tools_widget is None:
            self._maybe_auto_fold_step_tool_list()
            self._maybe_auto_collapse_step_card()
            self._sync_running_status_line()
            return
        if not STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            self._sync_running_status_line()
            return
        # IG-420: Throttle refreshes to prevent UI lag during streaming (only when mounted)
        if not force and not _should_refresh_now(self._last_tools_refresh):
            return
        self._last_tools_refresh = monotonic()
        if not self._rows:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            return
        self._maybe_auto_fold_step_tool_list()
        self._tools_widget.display = True
        ordered_rows = self._build_nested_row_order()
        show_all = len(ordered_rows) <= _STEP_TOOL_PREVIEW_ROWS or not self._tools_body_collapsed
        visible = ordered_rows if show_all else ordered_rows[:_STEP_TOOL_PREVIEW_ROWS]
        panel_key: tuple[Any, ...] = (
            tuple(self._row_content_cache_key(r) for r in visible),
            show_all,
            self._tools_body_collapsed,
        )
        if not force and panel_key == self._tools_panel_cache_key:
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            return
        lines: list[Content] = []
        for row in visible:
            rk = self._row_content_cache_key(row)
            if self._row_cache_key_by_id.get(row.tool_call_id) != rk:
                content = self._row_to_content(row)
                self._row_cache_key_by_id[row.tool_call_id] = rk
                self._row_content_by_id[row.tool_call_id] = content
            lines.append(self._row_content_by_id[row.tool_call_id])
        self._tools_panel_cache_key = panel_key
        self._tools_widget.update(Content("\n").join(lines))

        self._maybe_auto_collapse_step_card()
        self._sync_step_footer_hint()

    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        raw_args: str = "",
        parent_tool_call_id: str | None = None,  # IG-419
        is_task_row: bool = False,  # IG-419
    ) -> None:
        """Register a new tool row (pending).

        Args:
            tool_call_id: Unique tool call identifier.
            tool_name: Tool name for display.
            args: Parsed tool arguments.
            raw_args: Raw JSON args string from streaming (stored on the row for
                later merge when args arrive incrementally).
            parent_tool_call_id: IG-419: Link to parent task row for nesting.
            is_task_row: IG-419: Mark as task delegation parent row.
        """
        tcid = str(tool_call_id).strip()
        if not tcid:
            return
        # Only main-graph step-level ``task`` delegations are parent rows. Subgraph
        # ``{step}:t{n}:task:…`` streams must stay nested children (or be skipped).
        if not is_task_row and parent_tool_call_id is None:
            _, type_code, _, _ = parse_unified_tool_call_id(tcid)
            if is_step_level_task_tool_id(tcid) or (
                (tool_name or "").strip() == "task" and type_code != "t"
            ):
                is_task_row = True
        if is_task_row and is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                is_task_row = False
            else:
                canonical_tcid = normalize_step_task_tool_call_id(self._step_id, tcid)
                for existing_id, existing_row in list(self._row_index.items()):
                    if self._task_delegation_dedupe_key(existing_row) != canonical_tcid:
                        continue
                    if existing_id == canonical_tcid:
                        self.update_tool_args(canonical_tcid, args)
                        return
                    self._migrate_tool_row_id(existing_id, canonical_tcid)
                    self.update_tool_args(canonical_tcid, args)
                    return
                tcid = canonical_tcid
        if tcid in self._row_index:
            self.update_tool_args(tcid, args)
            return
        row_args: dict[str, Any] = dict(args or {})
        if raw_args:
            row_args["_raw"] = raw_args
        row = _StepToolRow(
            tool_call_id=tcid,
            tool_name=(tool_name or "tool").strip() or "tool",
            args=row_args,
            phase="pending",
            parent_tool_call_id=parent_tool_call_id,
            is_task_row=is_task_row,
        )
        if not is_task_row:
            _, type_code, task_idx, _ = parse_unified_tool_call_id(tcid)
            is_subgraph_tool = type_code == "t" or bool(parent_tool_call_id)
            if is_subgraph_tool:
                row.phase = "running"
                row.started_at = time()
                parent_key = ""
                if parent_tool_call_id:
                    parent_key = self._normalized_task_note_key(parent_tool_call_id)
                elif task_idx is not None:
                    for task_row in self._iter_task_delegation_rows():
                        if self._task_idx_from_delegation_row(task_row) == task_idx:
                            parent_key = self._task_delegation_dedupe_key(task_row)
                            break
                if parent_key:
                    self._touch_task_activity_start(parent_key)
        self._rows.append(row)
        self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)
        if is_task_row or parent_tool_call_id:
            self._refresh_task_activity_display()
        self._sync_running_status_line()

        self._promote_pending_to_running_if_needed()

    def _promote_pending_to_running_if_needed(self) -> None:
        """Show running UI when tools arrive before ``step.started`` (mounted cards)."""
        if self._status != "pending":
            return
        if getattr(self, "is_mounted", False):
            self.set_running()
            return
        self._status = "running"
        self._start_time = time()
        self._deferred_running = True

    def _canonical_task_lookup_key(self, tool_call_id: str) -> str | None:
        """Normalized task row key when ``tool_call_id`` denotes a step-level delegation."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return None
        if is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                return None
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return None

    def has_tool_call_row(self, tool_call_id: str) -> bool:
        """Return True if this step card already tracks ``tool_call_id`` (or its task alias)."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return False
        if tcid in self._row_index:
            return True
        task_key = self._canonical_task_lookup_key(tcid)
        if not task_key:
            return False
        if task_key in self._row_index:
            return True
        return any(
            self._task_delegation_dedupe_key(row) == task_key for row in self._row_index.values()
        )

    def _migrate_tool_row_id(self, old_id: str, new_id: str) -> None:
        """Rename a tracked tool row (e.g. provider id → unified step task id)."""
        old = str(old_id).strip()
        new = str(new_id).strip()
        if not old or not new or old == new:
            return
        row = self._row_index.pop(old, None)
        if row is None:
            return
        row.tool_call_id = new
        self._row_index[new] = row
        self._rows = [row if r.tool_call_id == old else r for r in self._rows]
        cache = self._row_content_by_id.pop(old, None)
        if cache is not None:
            self._row_content_by_id[new] = cache
        cache_key = self._row_cache_key_by_id.pop(old, None)
        if cache_key is not None:
            self._row_cache_key_by_id[new] = cache_key

    def pop_tool_row(self, tool_call_id: str) -> _StepToolRow | None:
        """Remove and return a tool row so another step card can adopt it (parallel routing)."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return None
        row = self._row_index.pop(tcid, None)
        if row is None:
            return None
        self._rows = [r for r in self._rows if r.tool_call_id != tcid]
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)

    def ingest_tool_row(self, row: _StepToolRow) -> None:
        """Attach a tool row moved from another step card."""
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return
        if tcid in self._row_index:
            self.update_tool_args(tcid, row.args)
            return
        self._rows.append(row)
        self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)
        self._sync_running_status_line()

        self._promote_pending_to_running_if_needed()

    def row_duration_ms_since_started(self, tool_call_id: str) -> int:
        """Elapsed ms since this row entered running state (for result lines)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.started_at is None:
            return 0
        return int((time() - row.started_at) * 1000)

    def update_tool_args(self, tool_call_id: str, args: dict[str, Any]) -> None:
        """Refresh kwargs when streaming fills in arguments."""
        from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict
        from soothe_cli.runtime.parse.tool_call_resolution import tool_args_meaningful

        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        incoming = extract_tool_args_dict(args or {})
        merged = dict(row.args or {})
        if incoming:
            merged.update(incoming)
        if not tool_args_meaningful(merged):
            return
        if merged == row.args:
            return
        row.args = merged
        self._rebuild_tool_stats()
        if row.is_task_row or is_step_level_task_tool_id(str(tool_call_id)):
            self._refresh_task_activity_display()
        self._sync_running_status_line()
        self.request_tools_display_refresh()

    def set_tool_running(self, tool_call_id: str) -> None:
        """Mark a tool row as executing (after approval)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.phase not in ("pending", "running"):
            return
        row.phase = "running"
        row.started_at = time()
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_success(self, tool_call_id: str, result: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as success."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "success"
        row.output = _strip_success_exit_line(result)
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_error(self, tool_call_id: str, error: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as error."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "error"
        row.output = error
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_rejected(self, tool_call_id: str) -> None:
        """Mark a tool row as rejected."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "rejected"
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_skipped(self, tool_call_id: str) -> None:
        """Mark a tool row skipped (batch reject / incomplete)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "skipped"
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def mark_unfinished_tools_skipped(self) -> None:
        """Mark pending/running rows skipped when the step ends without results."""
        for row in self._rows:
            if row.phase in ("pending", "running"):
                row.phase = "skipped"
                row.started_at = None
        self._refresh_task_activity_display()
        self._refresh_tools_display()

    def iter_open_tool_calls_for_interrupt(self) -> list[dict[str, Any]]:
        """Tool call dicts for interrupted AIMessage state (non-task rows only)."""
        out: list[dict[str, Any]] = []
        for row in self._rows:
            if row.phase in ("pending", "running"):
                out.append(
                    {
                        "id": row.tool_call_id,
                        "name": row.tool_name,
                        "args": dict(row.args),
                    }
                )
        return out

    def snapshot_tool_rows(self) -> list[dict[str, Any]]:
        """Serialize tool rows for ``MessageData`` (IG-402)."""
        return [
            {
                "id": r.tool_call_id,
                "name": r.tool_name,
                "args": dict(r.args),
                "phase": r.phase,
                "output": r.output,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at,
                "parent_tool_call_id": r.parent_tool_call_id,
                "is_task_row": r.is_task_row,
            }
            for r in self._rows
        ]

    def apply_tool_rows_snapshot(self, rows: list[dict[str, Any]]) -> None:
        """Restore tool rows from :meth:`snapshot_tool_rows` output."""
        self._rows = []
        self._row_index = {}
        self._stats_order = []
        self._stats_counts = {}
        for raw in rows or []:
            tcid = str(raw.get("id", "")).strip()
            if not tcid:
                continue
            name = str(raw.get("name", "tool") or "tool")
            args = raw.get("args")
            if not isinstance(args, dict):
                args = {}
            phase = str(raw.get("phase", "pending"))
            is_task = bool(raw.get("is_task_row")) or is_step_level_task_tool_id(tcid)
            parent = raw.get("parent_tool_call_id")
            parent_id = str(parent).strip() if parent else None
            row = _StepToolRow(
                tool_call_id=tcid,
                tool_name=name,
                args=dict(args),
                phase=phase,
                output=str(raw.get("output", "") or ""),
                duration_ms=int(raw.get("duration_ms", 0) or 0),
                started_at=raw.get("started_at"),
                parent_tool_call_id=parent_id,
                is_task_row=is_task,
            )
            self._rows.append(row)
            self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self._refresh_tools_display()

    def _sync_running_status_line(self) -> None:
        """Refresh status text when tool stats change without repainting tool rows."""
        if self._status == "running":
            self._update_running_animation()
        elif self._status == "queued":
            self._refresh_queued_display()
        elif self._status == "pending":
            self._refresh_pending_display()

    def _refresh_pending_display(self) -> None:
        """Show waiting state for planned steps that are not executing yet."""
        if self._status != "pending" or self._status_widget is None:
            return
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        line = f"{gutter}{g.circle_empty} Pending...{self._stats_title_suffix()}"
        self._status_widget.remove_class("queued")
        self._status_widget.add_class("pending")
        self._status_widget.update(Content.styled(line, colors.cognition))
        self._status_widget.display = True
        self._refresh_task_activity_display()

    def _refresh_queued_display(self) -> None:
        """Show ready steps waiting for a concurrency slot (``max_parallel_steps``)."""
        if self._status != "queued" or self._status_widget is None:
            return
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        line = f"{gutter}{g.circle_empty} Queued...{self._stats_title_suffix()}"
        self._status_widget.remove_class("pending")
        self._status_widget.add_class("queued")
        self._status_widget.update(Content.styled(line, colors.cognition))
        self._status_widget.display = True
        self._refresh_task_activity_display()

    def set_queued(self) -> None:
        """Mark a ready step as waiting for an execute batch slot."""
        if self._status in ("running", "success", "error"):
            return
        self._status = "queued"
        self._refresh_queued_display()

    def set_running(self) -> None:
        """Show animated running state (call after mount)."""
        if self._status == "running":
            return
        self._status = "running"
        self._step_card_user_expanded = False
        self._step_tool_list_user_expanded = False
        self._start_time = time()
        self._tools_body_collapsed = False
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.remove_class("queued")
            self._status_widget.display = True
        self._update_running_animation()
        self._refresh_task_activity_display()
        self._animation_timer = self.set_interval(
            _RUNNING_SPINNER_INTERVAL_SECONDS,
            self._update_running_animation,
        )

    def _stop_animation(self) -> None:
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def _update_running_animation(self) -> None:
        if self._status != "running" or self._status_widget is None:
            return
        if not _is_widget_animation_visible(self):
            return
        frames = get_glyphs().spinner_frames
        frame = frames[self._spinner_position]
        self._spinner_position = (self._spinner_position + 1) % len(frames)
        elapsed = ""
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        colors = theme.get_theme_colors(self)
        gutter = f"{get_glyphs().output_prefix} "
        # Expand/collapse affordance: collapsed → expand glyph; expanded → collapse glyph.
        has_collapsible = (
            (STEP_CARD_SHOW_TOOL_ROW_DETAILS and self._rows)
            or self._has_task_activity_body()
            or self._execute_assistant_buffer.strip()
        )
        g = get_glyphs()
        toggle_icon = ""
        if has_collapsible:
            toggle_icon = f" {g.expand if self._card_collapsed else g.collapse}"
        stats_suffix = self._stats_title_suffix()
        line = f"{gutter}{frame} Running...{elapsed}{stats_suffix}{toggle_icon}"
        clear_widget_text_selection(self._status_widget)
        self._status_widget.update(Content.styled(line, colors.cognition))
        if self._has_active_task_branch_animation():
            self._refresh_task_activity_display()

    def set_complete(
        self,
        success: bool,
        duration_ms: int,
        tool_call_count: int,
        summary: str,
    ) -> None:
        """Finalize step with duration, tool count, and summary text."""
        self._stop_animation()
        self._status = "success" if success else "error"
        self._last_success = success
        self._last_duration_ms = duration_ms
        self._last_tool_call_count = tool_call_count
        self._last_summary = summary.strip()
        if self._status_widget is None or self._detail_widget is None:
            self._deferred_complete = (success, duration_ms, tool_call_count, summary)
            return

        self.mark_unfinished_tools_skipped()
        self._tools_body_collapsed = True
        self._refresh_tools_display(force=True)

        dur_str = format_duration_ms(duration_ms)
        tool_part = self._status_tool_stats_suffix(tool_call_count)

        prose = self._execute_assistant_buffer.strip()
        self._last_completed_execute_prose = prose
        self._execute_assistant_buffer = ""

        if success:
            status_body = f"Completed ({dur_str}){tool_part}"
            self._update_step_footer_status_line(status_body, success=True)
            if prose:
                self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                self._detail_widget.display = True
            else:
                self._detail_widget.display = False
            self._maybe_auto_collapse_step_card()
            return

        err_text = summary.strip() or "Step failed"
        self._update_step_footer_status_line(f"Failed · {dur_str}", success=False)
        if prose:
            err_text = f"{err_text}\n\n{prose}"
        self._detail_widget.update(self._step_branched_error_detail(err_text))
        self._detail_widget.display = True
        self._maybe_auto_collapse_step_card()

    def set_result_preview(self, text: str) -> None:
        """Show a 3-line preview of the goal_completion result in the detail area."""
        if not text.strip():
            return
        lines = text.strip().splitlines()
        preview_lines = lines[:3]
        preview = "\n".join(preview_lines)
        remaining = len(lines) - 3
        if remaining > 0:
            ellipsis = get_glyphs().ellipsis
            preview += f"\n{ellipsis} {remaining} more lines"
        if self._detail_widget is None:
            return
        g = get_glyphs()
        sub = f"{g.output_prefix} {g.circle_empty} "
        assembled: list[object] = []
        if self._last_success is not None:
            dur_str = format_duration_ms(self._last_duration_ms)
            tool_part = self._status_tool_stats_suffix(self._last_tool_call_count)
            self._update_step_footer_status_line(f"Completed ({dur_str}){tool_part}", success=True)
        first_pv = True
        for ln in preview.splitlines():
            if not first_pv:
                assembled.append("\n")
            first_pv = False
            assembled.append(Content.styled(f"{sub}{ln}", "dim"))
        self._detail_widget.update(Content.assemble(*assembled))
        self._detail_widget.display = True

    def set_interrupted(self, message: str) -> None:
        """Mark step as aborted (stream error / cancel) while still running."""
        self._stop_animation()
        self._status = "error"
        self._execute_assistant_buffer = ""
        self._last_completed_execute_prose = ""
        self._interrupt_message = message
        for row in self._rows:
            if row.phase in ("pending", "running"):
                row.phase = "skipped"
                row.started_at = None
        self._refresh_tools_display()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001  # Unmounted widget (tests / no Textual app)
            colors = theme.DARK_COLORS
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.add_class("error")
            self._status_widget.update(Content.styled(message, colors.error))
            self._status_widget.display = True
        if self._detail_widget:
            self._detail_widget.display = False


class CognitionReasonMessage(_TimestampClickMixin, Vertical):
    """Single card for plan assessment, plan reasoning, and next action (keep/new).

    Header uses the same cognition-colored label plus foreground body as ``CognitionStepMessage``.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionReasonMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionReasonMessage .cognition-plan-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionReasonMessage .plan-section-line {
        height: auto;
        margin-left: 3;
        color: $text-muted;
    }

    CognitionReasonMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    def __init__(
        self,
        *,
        next_action: str,
        status: str,
        iteration: int,
        plan_action: str = "new",
        assessment_reasoning: str = "",
        plan_reasoning: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a plan-reason card.

        Args:
            next_action: User-facing next step line.
            status: Plan status (continue, replan, done).
            iteration: Agent-loop iteration index.
            plan_action: ``keep`` or ``new`` (execution strategy).
            assessment_reasoning: Phase-1 status justification.
            plan_reasoning: Phase-2 plan-strategy text.
            **kwargs: Passed to ``Vertical``.
        """
        super().__init__(**kwargs)
        self._next_action = next_action.strip()
        self._status = status
        self._iteration = iteration
        self._plan_action = plan_action if plan_action in ("keep", "new") else ""
        self._assessment_reasoning = assessment_reasoning.strip()
        self._plan_reasoning = plan_reasoning.strip()

    def _plan_header_content(self) -> Content:
        # Assess-only card: only assessment_reasoning populated
        if self._assessment_reasoning and not self._plan_reasoning and not self._next_action:
            return _assemble_card_header(self, "💭 ", self._assessment_reasoning)

        # Concatenate plan_reasoning and next_action with proper separation
        parts: list[str] = []
        if self._plan_reasoning:
            parts.append(self._plan_reasoning)
        if self._next_action:
            parts.append(self._next_action)
        # Join with period and space if both present, ensuring proper sentence separation
        if len(parts) == 2:
            # Ensure plan_reasoning ends with period before adding next_action
            pr = parts[0]
            if not pr.endswith((".", "!", "?")):
                pr = f"{pr}."
            body = f"{pr} {parts[1]}"
        elif parts:
            body = parts[0]
        else:
            body = ""
        if self._plan_action in ("keep", "new"):
            body = f"{body} · {self._plan_action}"
        return _assemble_card_header(self, "💭 ", body)

    def compose(self) -> ComposeResult:
        yield Static(self._plan_header_content(), classes="cognition-plan-header")

    def on_mount(self) -> None:
        """Use ASCII border variant when configured."""
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)


_MAX_GOAL_HEADER = 100
_MAX_GOAL_STEP_DESC = 200


class _StepLineState:
    """Mutable row state for the goal → steps aggregate."""

    __slots__ = (
        "step_id",
        "description",
        "phase",
        "success",
        "duration_ms",
        "tool_call_count",
        "summary",
    )

    def __init__(
        self,
        step_id: str,
        description: str,
        *,
        phase: str = "running",
        success: bool = True,
        duration_ms: int = 0,
        tool_call_count: int = 0,
        summary: str = "",
    ) -> None:
        self.step_id = step_id
        self.description = description
        self.phase = phase
        self.success = success
        self.duration_ms = duration_ms
        self.tool_call_count = tool_call_count
        self.summary = summary


class CognitionGoalTreeMessage(_TimestampClickMixin, Vertical):
    """Two-level Goal → steps tree; one aggregate block updates in place.

    Title line matches ``CognitionStepMessage`` / ``CognitionReasonMessage``:
    ``{prefix} 📍 …`` with optional ``· iter<=N`` when ``max_iterations`` is set.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionGoalTreeMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-steps {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-footer {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionGoalTreeMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    def __init__(
        self,
        *,
        goal: str,
        max_iterations: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize an empty goal tree (steps render as events arrive).

        Args:
            goal: Primary goal text (clipped for header).
            max_iterations: Shown in header when greater than 1.
            **kwargs: Passed to ``Vertical``.
        """
        super().__init__(**kwargs)
        self._goal_text = goal.strip()
        self._max_iterations = int(max_iterations)
        self._step_order: list[str] = []
        self._steps: dict[str, _StepLineState] = {}
        self._footer_plain: str = ""
        self._footer_visible: bool = False
        self._footer_tone: str = "muted"  # success | error | muted (step/tool completion parity)
        self._steps_static: Static | None = None

    @staticmethod
    def _clip(text: str, max_len: int) -> str:
        t = (text or "").strip().replace("\n", " ")
        if len(t) <= max_len:
            return t
        return t[: max_len - 1].rstrip() + "…"

    def _goal_header_content(self) -> Content:
        g = self._clip(self._goal_text, _MAX_GOAL_HEADER)
        body = g
        if self._max_iterations > 1:
            body = f"{body} · iter<={self._max_iterations}"
        return _assemble_card_header(self, "📍 ", body)

    def _goal_footer_styled_content(self) -> Content:
        """Footer content for loop finished / interrupted (parity with step/tool status lines)."""
        if not self._footer_visible or not self._footer_plain:
            return Content("")
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = f"{get_glyphs().output_prefix} "
        plain = self._footer_plain
        if self._footer_tone == "success":
            mark = get_glyphs().checkmark
            return Content.styled(f"{gutter}{mark} {plain}", colors.cognition)
        if self._footer_tone == "error":
            mark = get_glyphs().error
            return Content.styled(f"{gutter}{mark} {plain}", colors.error)
        return Content.styled(f"{gutter}{plain}", "dim")

    def _indent_prefix(self) -> str:
        g = get_glyphs()
        return f"{g.output_prefix} "

    def _goal_tree_step_line_content(self, st: _StepLineState) -> Content:
        """One goal→step row: dim tree gutter, foreground body (parity with ``CognitionStepMessage`` tool rows)."""
        g = get_glyphs()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = self._indent_prefix()
        body = self._clip(st.description, _MAX_GOAL_STEP_DESC)
        if st.phase == "running":
            rest = f"{g.circle_empty} {body}"
        else:
            icon = g.checkmark if st.success else g.error
            dur_s = max(0.001, st.duration_ms / 1000.0)
            dur = format_duration(dur_s)
            rest = f"{icon} {body} · {dur}"
            if st.tool_call_count > 0:
                rest += f" · {st.tool_call_count} tools"
            tail = (st.summary or "").strip()
            if tail and tail not in ("Done", "Failed"):
                rest += f" — {self._clip(tail, 80)}"
        if st.phase == "error" or (st.phase == "done" and not st.success):
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, colors.error),
            )
        return Content.assemble(
            Content.styled(gutter, "dim"),
            Content.styled(rest, colors.foreground),
        )

    def _refresh_steps_display(self) -> None:
        if self._steps_static is None:
            return
        line_contents: list[Content] = []
        for sid in self._step_order:
            st = self._steps.get(sid)
            if st is None:
                continue
            line_contents.append(self._goal_tree_step_line_content(st))
        if not line_contents:
            self._steps_static.update(Content(""))
            return
        parts: list[object] = []
        for i, c in enumerate(line_contents):
            if i:
                parts.append("\n")
            parts.append(c)
        self._steps_static.update(Content.assemble(*parts))

    def compose(self) -> ComposeResult:
        yield Static(
            self._goal_header_content(),
            id="cognition-goal-tree-header",
            classes="cognition-goal-tree-header",
        )
        yield Static("", id="cognition-goal-tree-steps", classes="cognition-goal-tree-steps")
        yield Static("", id="cognition-goal-tree-footer", classes="cognition-goal-tree-footer")

    def on_mount(self) -> None:
        """Wire step aggregate; sync static children from in-memory state."""
        self._steps_static = self.query_one("#cognition-goal-tree-steps", Static)
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
        self._sync_goal_tree_widgets()

    def _sync_goal_tree_widgets(self) -> None:
        """Push goal, steps, and footer state to child widgets (requires mount)."""
        try:
            hdr = self.query_one("#cognition-goal-tree-header", Static)
            hdr.update(self._goal_header_content())
        except Exception:
            logger.debug("goal tree header sync failed", exc_info=True)
        try:
            ft = self.query_one("#cognition-goal-tree-footer", Static)
            if self._footer_visible and self._footer_plain:
                ft.update(self._goal_footer_styled_content())
                ft.display = True
            else:
                ft.display = False
        except Exception:
            logger.debug("goal tree footer sync failed", exc_info=True)
        self._refresh_steps_display()

    def snapshot_dict(self) -> dict[str, Any]:
        """Serialize tree state for the message store."""
        steps_out: list[dict[str, Any]] = []
        for sid in self._step_order:
            st = self._steps.get(sid)
            if st is None:
                continue
            steps_out.append(
                {
                    "id": st.step_id,
                    "description": st.description,
                    "phase": st.phase,
                    "success": st.success,
                    "duration_ms": st.duration_ms,
                    "tool_call_count": st.tool_call_count,
                    "summary": st.summary,
                }
            )
        return {
            "goal": self._goal_text,
            "max_iterations": self._max_iterations,
            "steps": steps_out,
            "footer_visible": self._footer_visible,
            "footer_text": self._footer_plain,
            "footer_tone": self._footer_tone,
        }

    def _apply_snapshot(self, snap: dict[str, Any]) -> None:
        """Restore in-memory goal tree state from :meth:`snapshot_dict` output."""
        self._goal_text = str(snap.get("goal", self._goal_text))
        self._max_iterations = int(snap.get("max_iterations", self._max_iterations))
        self._footer_plain = str(snap.get("footer_text", ""))
        self._footer_visible = bool(snap.get("footer_visible", False))
        tone = str(snap.get("footer_tone", "muted") or "muted")
        self._footer_tone = tone if tone in ("success", "error", "muted") else "muted"
        self._step_order = []
        self._steps.clear()
        for row in snap.get("steps", []) or []:
            sid = str(row.get("id", "")).strip()
            if not sid:
                continue
            st = _StepLineState(
                sid,
                str(row.get("description", "")),
                phase=str(row.get("phase", "running")),
                success=bool(row.get("success", True)),
                duration_ms=int(row.get("duration_ms", 0)),
                tool_call_count=int(row.get("tool_call_count", 0)),
                summary=str(row.get("summary", "")),
            )
            self._step_order.append(sid)
            self._steps[sid] = st

    def add_step_running(self, step_id: str, description: str) -> None:
        """Register a step in running state and refresh the aggregate."""
        sid = step_id.strip()
        if not sid:
            return
        desc = (description or "").strip() or "(step)"
        if sid not in self._steps:
            self._step_order.append(sid)
        self._steps[sid] = _StepLineState(sid, desc, phase="running")
        self._refresh_steps_display()

    def complete_step(
        self,
        step_id: str,
        success: bool,
        duration_ms: int,
        tool_call_count: int,
        summary: str,
    ) -> None:
        """Update a step row to its final state."""
        sid = step_id.strip()
        if not sid:
            return
        st = self._steps.get(sid)
        if st is None:
            self._step_order.append(sid)
            st = _StepLineState(sid, "(step)", phase="running")
            self._steps[sid] = st
        st.phase = "done" if success else "error"
        st.success = success
        st.duration_ms = duration_ms
        st.tool_call_count = tool_call_count
        st.summary = summary or ""
        self._refresh_steps_display()

    def set_loop_finished(
        self,
        *,
        status: str,
        goal_progress: str,  # IG-399: descriptive level instead of float
        completion_summary: str,
        total_steps: int,
    ) -> None:
        """Show a compact footer when the agentic loop completes."""
        # IG-399: Map descriptive levels to percentage display
        progress_map = {
            "none": "0%",
            "low": "20%",
            "medium": "50%",
            "high": "80%",
            "complete": "100%",
        }
        gp_key = str(goal_progress or "").strip().lower()
        pct_display = progress_map.get(gp_key, "0%")
        status_str = str(status or "done")
        status_str = status_str[:1].upper() + status_str[1:] if status_str else status_str
        parts: list[str] = [status_str, pct_display]
        if total_steps:
            parts.append(f"{total_steps} step(s)")
        cs = (completion_summary or "").strip()
        if cs:
            parts.append(self._clip(cs, 100))
        self._footer_plain = " · ".join(parts)
        self._footer_visible = True
        status_l = str(status or "").strip().lower()
        if status_l == "done":
            self._footer_tone = "success"
        elif status_l in ("failed", "error", "fatal"):
            self._footer_tone = "error"
        else:
            self._footer_tone = "muted"
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(self._goal_footer_styled_content())
            footer.display = True
        except Exception:
            pass

    def set_interrupted(self, message: str) -> None:
        """Mark running steps as failed and show a footer (stream cancel/error)."""
        msg = (message or "Interrupted").strip()
        for sid in list(self._step_order):
            st = self._steps.get(sid)
            if st is not None and st.phase == "running":
                st.phase = "error"
                st.success = False
                st.duration_ms = 0
                st.summary = msg
        self._refresh_steps_display()
        self._footer_plain = self._clip(msg, 120)
        self._footer_visible = True
        self._footer_tone = "error"
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(self._goal_footer_styled_content())
            footer.display = True
        except Exception:
            pass


class ErrorMessage(_TimestampClickMixin, Static):
    """Widget displaying an error message."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    ErrorMessage {
        height: auto;
        padding: 1;
        margin: 0 0 1 0;
        background: $error-muted;
        color: white;
        border-left: wide $error;
    }
    """
    """Tinted background + left border to visually separate errors from output."""

    def __init__(self, error: str, **kwargs: Any) -> None:
        """Initialize an error message.

        Args:
            error: The error message
            **kwargs: Additional arguments passed to parent
        """
        # Store raw content for serialization
        self._content = error
        super().__init__(**kwargs)

    def render(self) -> Content:
        """Render with theme-aware colors.

        Returns:
            Styled error content with theme-appropriate color.
        """
        colors = theme.get_theme_colors(self)
        return Content.assemble(
            Content.styled("Error: ", f"bold {colors.error}"),
            self._content,
        )

    def on_mount(self) -> None:
        """Set border style based on charset mode."""
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border_left = ("ascii", colors.error)


class AppMessage(Static):
    """Widget displaying an app message."""

    # Disable Textual's auto_links to prevent a flicker cycle: Style.__add__
    # calls .copy() for linked styles, generating a fresh random _link_id on
    # each render. This means highlight_link_id never stabilizes, causing an
    # infinite hover-refresh loop.
    auto_links = False

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    AppMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, message: str | Content, **kwargs: Any) -> None:
        """Initialize a system message.

        Args:
            message: The system message as a string or pre-styled `Content`.
            **kwargs: Additional arguments passed to parent
        """
        # Store raw content for serialization
        self._content = message
        rendered = (
            message if isinstance(message, Content) else Content.styled(message, "dim italic")
        )
        super().__init__(rendered, **kwargs)

    def on_click(self, event: Click) -> None:
        """Open style-embedded hyperlinks on single click and show timestamp."""
        if _click_has_text_selection(self):
            return
        open_style_link(event)
        _show_timestamp_toast(self)


class SummarizationMessage(AppMessage):
    """Widget displaying a summarization completion notification."""

    DEFAULT_CSS = """
    SummarizationMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $primary;
        background: $surface;
        border-left: wide $primary;
        text-style: bold;
    }
    """

    def __init__(self, message: str | Content | None = None, **kwargs: Any) -> None:
        """Initialize a summarization notification message.

        Args:
            message: Optional message override used when rehydrating from the
                message store.

                Defaults to the standard summary notification.
            **kwargs: Additional arguments passed to parent.
        """
        self._raw_message = message
        # Pass the default text to AppMessage for _content serialization;
        # render() supplies theme-aware styling at display time.
        super().__init__(message or "Conversation summarized", **kwargs)

    def render(self) -> Content:
        """Render with theme-aware colors.

        Returns:
            Styled summarization content with theme-appropriate color.
        """
        colors = theme.get_theme_colors(self)
        if self._raw_message is None:
            return Content.styled("Conversation summarized", f"bold {colors.primary}")
        if isinstance(self._raw_message, Content):
            return self._raw_message
        return Content.styled(self._raw_message, f"bold {colors.primary}")
