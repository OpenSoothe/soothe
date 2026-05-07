"""Message widgets for Soothe."""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any

from soothe_sdk.utils import get_tool_display_name
from textual import on
from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.reactive import var
from textual.widgets import Static

from soothe_cli.shared.core.presentation_engine import PresentationEngine
from soothe_cli.shared.tools.message_processing import _normalize_tool_name_for_arg_map
from soothe_cli.shared.tools.tool_call_resolution import infer_tool_name_from_call_id
from soothe_cli.tui import theme
from soothe_cli.tui.config import (
    MODE_DISPLAY_GLYPHS,
    PREFIX_TO_MODE,
    get_glyphs,
    is_ascii_mode,
)
from soothe_cli.tui.formatting import format_duration
from soothe_cli.tui.input import EMAIL_PREFIX_PATTERN, INPUT_HIGHLIGHT_PATTERN
from soothe_cli.tui.preview_limits import (
    APPROVAL_DIFF_MAX_LINES,
    ASSISTANT_MESSAGE_PREVIEW_CHARS,
    ASSISTANT_MESSAGE_PREVIEW_LINES,
    SKILL_CARD_PREVIEW_CHARS,
    SKILL_CARD_PREVIEW_LINES,
    TOOL_CARD_PREVIEW_CHARS,
    TOOL_CARD_PREVIEW_LINES,
    TOOL_CARD_PREVIEW_TODO_ITEMS,
    TOOL_CARD_PREVIEW_WEB_DICT_KEYS,
)
from soothe_cli.tui.tool_display import format_tool_call_row, format_tool_cli_style_command
from soothe_cli.tui.widgets._links import open_style_link
from soothe_cli.tui.widgets.diff import compose_diff_lines

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer
    from textual.widgets import Markdown
    from textual.widgets._markdown import MarkdownStream

logger = logging.getLogger(__name__)

_STEP_TOOL_PREVIEW_ROWS = 3
"""Collapsed step-card tool list shows this many rows (IG-402)."""

_MAX_STEP_STAT_TOOL_KINDS = 4
"""Max distinct tool display names in the step header before ``+N more``."""


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


# Truncation limits for display
_MAX_TODO_CONTENT_LEN = 70
_MAX_WEB_CONTENT_LEN = 100

_TOOL_CARD_PRESENTATION = PresentationEngine()
"""Shared brief/summary rules with headless CLI (IG-320)."""

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

    can_select = True
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
        glyphs = get_glyphs()
        role_icon = glyphs.user if not is_ascii_mode() else ">"
        parts.append((f"{role_icon}  ", f"bold {colors.primary}"))

        # Use mode-specific prefix indicator when content starts with a
        # mode trigger character (e.g. "!" for shell, "/" for commands).
        # The display glyph may differ from the trigger (e.g. "$" for shell).
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            parts.append((f"{glyph} ", f"bold {_mode_color(mode, self)}"))
            content = content[1:]
        else:
            # Add subtle separator for non-mode messages
            parts.append(("│ ", f"dim {colors.muted}"))

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

    can_select = True
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

    can_select = True
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
                        f"{ellipsis} {remaining} more lines — click or Ctrl+O to expand",
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
            self._hint_widget.update(Content.styled("click or Ctrl+O to collapse", "dim italic"))
        else:
            remaining = total_lines - self._PREVIEW_LINES
            ellipsis = get_glyphs().ellipsis
            self._hint_widget.update(
                Content.styled(
                    f"{ellipsis} {remaining} more lines — click or Ctrl+O to expand",
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
    """Assistant reply card: ``⏺`` header (same glyph as tool rows) and markdown body.

    Long bodies show the first few source lines collapsed (like ``ToolCallMessage``);
    click the card or use Ctrl+O (after skills) to expand or collapse. While the
    markdown stream is active, the full body stays visible until streaming stops.
    """

    can_select = True
    """Enable text selection for copy functionality."""

    _PREVIEW_LINES = ASSISTANT_MESSAGE_PREVIEW_LINES
    _PREVIEW_CHARS = ASSISTANT_MESSAGE_PREVIEW_CHARS

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $tool;
    }

    AssistantMessage .assistant-header {
        height: auto;
        color: $tool;
        text-style: bold;
    }

    AssistantMessage Markdown {
        padding: 0;
        margin: 0;
    }

    AssistantMessage .assistant-preview {
        margin-left: 0;
        margin-top: 0;
    }

    AssistantMessage .assistant-hint {
        margin-left: 0;
        color: $text-muted;
        background: transparent;
    }

    AssistantMessage:hover {
        border-left: wide $tool-hover;
        opacity: 0.95;
    }
    """

    def __init__(
        self,
        content: str = "",
        *,
        role_label: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize an assistant message.

        Args:
            content: Initial markdown content.
            role_label: Short label after the tool-style glyph (default ``Assistant``).
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
        label = (role_label or "Assistant").strip()
        self._role_label = label or "Assistant"
        self._content = content
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        self._expanded: bool = False
        self._header_widget: Static | None = None
        self._preview_widget: Static | None = None
        self._hint_widget: Static | None = None

    def compose(self) -> ComposeResult:  # noqa: PLR6301  # Textual widget method convention
        """Compose header, markdown body, plain preview, and expand hint."""
        from textual.widgets import Markdown

        yield Static("", markup=False, classes="assistant-header", id="assistant-header")
        yield Markdown("", id="assistant-md")
        yield Static("", markup=False, classes="assistant-preview", id="assistant-preview")
        yield Static("", markup=False, classes="assistant-hint", id="assistant-hint")

    def on_mount(self) -> None:
        """Wire child widgets and apply initial layout."""
        from textual.widgets import Markdown

        if is_ascii_mode():
            self.add_class("-ascii")

        self._markdown = self.query_one("#assistant-md", Markdown)
        self._header_widget = self.query_one("#assistant-header", Static)
        self._preview_widget = self.query_one("#assistant-preview", Static)
        self._hint_widget = self.query_one("#assistant-hint", Static)

        prefix = get_glyphs().tool_prefix
        self._header_widget.update(f"{prefix} {self._role_label}")
        self._preview_widget.display = False
        self._hint_widget.display = False
        self._refresh_body_visibility()

    def _needs_truncation(self, text: str) -> bool:
        raw = text or ""
        if not raw.strip():
            return False
        lines = raw.split("\n")
        if len(lines) > self._PREVIEW_LINES:
            return True
        return len(raw) > self._PREVIEW_CHARS

    def _preview_plain(self, text: str) -> str:
        lines = (text or "").split("\n")
        return "\n".join(lines[: self._PREVIEW_LINES])

    def _refresh_body_visibility(self) -> None:
        """Show markdown, plain preview, or hint depending on stream and collapse state."""
        md = self._markdown
        prev = self._preview_widget
        hint = self._hint_widget
        if md is None or prev is None or hint is None:
            return

        streaming = self._stream is not None
        body = self._content or ""
        if not body.strip():
            md.display = True
            prev.display = False
            hint.display = False
            return

        need = self._needs_truncation(body)
        if streaming or not need or self._expanded:
            md.display = True
            prev.display = False
            if need and not streaming and self._expanded:
                ellipsis = get_glyphs().ellipsis
                hint.update(
                    Content.styled(
                        f"{ellipsis} click or Ctrl+O to collapse",
                        "dim italic",
                    )
                )
                hint.display = True
            else:
                hint.display = False
            return

        md.display = False
        prev.update(self._preview_plain(body))
        prev.display = True
        total_lines = len(body.split("\n"))
        remaining = max(0, total_lines - self._PREVIEW_LINES)
        ellipsis = get_glyphs().ellipsis
        if remaining > 0:
            hint_line = (
                f"{ellipsis} {remaining} more lines — click or Ctrl+O to expand"
                if remaining != 1
                else f"{ellipsis} 1 more line — click or Ctrl+O to expand"
            )
        elif len(body) > self._PREVIEW_CHARS:
            hint_line = f"{ellipsis} more text — click or Ctrl+O to expand"
        else:
            hint_line = "click or Ctrl+O to expand"
        hint.update(Content.styled(hint_line, "dim"))
        hint.display = True

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

    @property
    def has_collapsible_body(self) -> bool:
        """True when the body is long enough to support expand/collapse."""
        return self._needs_truncation(self._content)

    def toggle_collapse(self) -> None:
        """Toggle expanded markdown vs collapsed plain preview."""
        if not self.has_collapsible_body:
            return
        self._expanded = not self._expanded
        self._refresh_body_visibility()

    def on_click(self, event: Click) -> None:
        """Toggle collapse for long messages; otherwise show timestamp toast."""
        event.stop()
        if self.has_collapsible_body:
            self.toggle_collapse()
        else:
            _show_timestamp_toast(self)

    async def append_content(self, text: str) -> None:
        """Append content to the message (for streaming)."""
        if not text:
            return
        self._content += text
        stream = self._ensure_stream()
        self._refresh_body_visibility()
        await stream.write(text)

    async def write_initial_content(self) -> None:
        """Write initial content from constructor and finalize the stream."""
        if self._content:
            stream = self._ensure_stream()
            await stream.write(self._content)
            await self.stop_stream()

    async def stop_stream(self) -> None:
        """Stop the streaming and apply collapsed layout when appropriate."""
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
        self._refresh_body_visibility()

    async def set_content(self, content: str) -> None:
        """Set the full message content (stops any active stream)."""
        await self.stop_stream()
        self._content = content
        if self._markdown:
            await self._markdown.update(content)
        self._refresh_body_visibility()


class ToolCallMessage(Vertical):
    """Widget displaying a tool call with CLI-style command and result lines.

    Command and result lines use the shared flat tool formatters (IG-320). Raw tool output is collapsed
    until the user expands (click or Ctrl+O). While pending, shows a running spinner.
    """

    can_select = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    ToolCallMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $tool;
    }

    ToolCallMessage .tool-header {
        height: auto;
        color: $tool;
        text-style: bold;
    }

    ToolCallMessage .tool-subagent-notes {
        margin-left: 3;
        color: $text-muted;
        height: auto;
    }

    ToolCallMessage .tool-status {
        margin-left: 3;
    }

    ToolCallMessage .tool-status.pending {
        color: $warning;
    }

    ToolCallMessage .tool-status.success {
        color: $success;
    }

    ToolCallMessage .tool-status.error {
        color: $error;
    }

    ToolCallMessage .tool-status.rejected {
        color: $warning;
    }

    ToolCallMessage .tool-result-summary {
        margin-left: 3;
        height: auto;
    }

    ToolCallMessage .tool-result-summary.success {
        color: $success;
    }

    ToolCallMessage .tool-result-summary.error {
        color: $error;
    }

    ToolCallMessage .tool-output {
        margin-left: 0;
        margin-top: 0;
        padding: 0;
        height: auto;
    }

    ToolCallMessage .tool-output-preview {
        margin-left: 0;
        margin-top: 0;
    }

    ToolCallMessage .tool-output-hint {
        margin-left: 0;
        color: $text-muted;
        background: transparent;
    }

    ToolCallMessage:hover {
        border-left: wide $tool-hover;
    }
    """
    """Left border tracks tool lifecycle; hover brightens for interactivity."""

    # Max lines/chars to show in preview mode (see ``preview_limits``)
    _PREVIEW_LINES = TOOL_CARD_PREVIEW_LINES
    _PREVIEW_CHARS = TOOL_CARD_PREVIEW_CHARS

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize a tool call message.

        Args:
            tool_name: Name of the tool being called
            args: Tool arguments (optional)
            tool_call_id: Provider tool-call id (e.g. ``functions.ls:0``) used to recover
                the real tool name when ``tool_name`` is empty or the placeholder ``tool``.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        tn = (tool_name or "").strip()
        tcid = (tool_call_id or "").strip()
        if tcid and (not tn or tn == "tool"):
            inferred = infer_tool_name_from_call_id(tcid)
            if inferred:
                tn = inferred
        if not tn:
            tn = "tool"
        self._tool_name = tn
        self._args = args or {}
        self._subagent_notes: list[str] = []
        self._status = "pending"  # Waiting for approval or auto-approve
        self._output: str = ""
        self._expanded: bool = False
        # Widget references (set in on_mount)
        self._status_widget: Static | None = None
        self._result_summary_widget: Static | None = None
        self._preview_widget: Static | None = None
        self._hint_widget: Static | None = None
        self._full_widget: Static | None = None
        # Animation state
        self._spinner_position = 0
        self._start_time: float | None = None
        self._animation_timer: Timer | None = None
        # Deferred state for hydration (set by MessageData.to_widget)
        self._deferred_status: str | None = None
        self._deferred_output: str | None = None
        self._deferred_expanded: bool = False

    def compose(self) -> ComposeResult:
        """Compose the tool call message layout.

        Yields:
            Widgets for header, CLI-style result line, status, and collapsible output.
        """
        tool_label = format_tool_cli_style_command(self._tool_name, self._args)
        yield Static(tool_label, markup=False, classes="tool-header")
        yield Static("", markup=False, classes="tool-subagent-notes", id="subagent-notes")
        yield Static("", classes="tool-result-summary", id="tool-result-summary")
        # Status — running spinner while executing; unused when result summary shows
        yield Static("", classes="tool-status", id="status")
        yield Static("", classes="tool-output-preview", id="output-preview")
        yield Static("", classes="tool-output", id="output-full")
        yield Static("", classes="tool-output-hint", id="output-hint")

    def on_mount(self) -> None:
        """Cache widget references and hide all status/output areas initially."""
        if is_ascii_mode():
            self.add_class("-ascii")

        self._status_widget = self.query_one("#status", Static)
        self._result_summary_widget = self.query_one("#tool-result-summary", Static)
        notes = self.query_one("#subagent-notes", Static)
        notes.display = False
        self._preview_widget = self.query_one("#output-preview", Static)
        self._hint_widget = self.query_one("#output-hint", Static)
        self._full_widget = self.query_one("#output-full", Static)
        # Hide everything initially - status only shown when running or on error/reject
        self._status_widget.display = False
        self._result_summary_widget.display = False
        self._preview_widget.display = False
        self._hint_widget.display = False
        self._full_widget.display = False

        # Restore deferred state if this widget was hydrated from data
        self._restore_deferred_state()

    def _restore_deferred_state(self) -> None:
        """Restore state from deferred values (used when hydrating from data)."""
        if self._deferred_status is None:
            return

        status = self._deferred_status
        output = self._deferred_output or ""
        self._expanded = self._deferred_expanded

        # Clear deferred values
        self._deferred_status = None
        self._deferred_output = None
        self._deferred_expanded = False

        # Restore based on status (don't restart animations for running tools)
        colors = theme.get_theme_colors(self)
        match status:
            case "success":
                self._status = "success"
                self._output = output
                if self._status_widget:
                    self._status_widget.remove_class("pending")
                    self._status_widget.display = False
                line = _TOOL_CARD_PRESENTATION.format_tool_result_status_line(
                    self._tool_name,
                    output,
                    is_error=False,
                    duration_ms=0,
                )
                self._apply_result_summary(line, is_error=False)
                self._update_output_display()
            case "error":
                self._status = "error"
                self._output = output
                if self._status_widget:
                    self._status_widget.remove_class("pending")
                    self._status_widget.remove_class("error")
                    self._status_widget.display = False
                line = _TOOL_CARD_PRESENTATION.format_tool_result_status_line(
                    self._tool_name,
                    output,
                    is_error=True,
                    duration_ms=0,
                )
                self._apply_result_summary(line, is_error=True)
                self._update_output_display()
            case "rejected":
                self._status = "rejected"
                if self._result_summary_widget:
                    self._result_summary_widget.display = False
                if self._status_widget:
                    self._status_widget.add_class("rejected")
                    error_icon = get_glyphs().error
                    self._status_widget.update(
                        Content.styled(f"{error_icon} Rejected", colors.warning)
                    )
                    self._status_widget.display = True
            case "skipped":
                self._status = "skipped"
                if self._result_summary_widget:
                    self._result_summary_widget.display = False
                if self._status_widget:
                    self._status_widget.add_class("rejected")
                    self._status_widget.update(Content.styled("- Skipped", "dim"))
                    self._status_widget.display = True
            case "running":
                # For running tools, show static "Running..." without animation
                # (animations shouldn't be restored for archived tools)
                self._status = "running"
                if self._result_summary_widget:
                    self._result_summary_widget.display = False
                if self._status_widget:
                    self._status_widget.add_class("pending")
                    frame = get_glyphs().spinner_frames[0]
                    self._status_widget.update(
                        Content.styled(f"{frame} Running...", colors.warning)
                    )
                    self._status_widget.display = True
            case _:
                # pending or unknown - leave as default
                pass

    def refresh_tool_args(self, args: dict[str, Any]) -> None:
        """Update displayed arguments when they arrive after the card was first mounted.

        Streaming providers sometimes emit a first chunk with ``args: {{}}``; real
        kwargs follow on later chunks. The adapter may mount early and then call
        this when a fuller argument dict is available.
        """
        self._args = args or {}
        try:
            header = self.query_one(".tool-header", Static)
        except Exception:  # noqa: BLE001  # Widget tree not ready or query miss
            return
        # Textual ``Static.update`` accepts only the new content (no ``markup=`` kwarg).
        header.update(format_tool_cli_style_command(self._tool_name, self._args))

    def append_subagent_activity(self, line: str) -> None:
        """Append one metadata line for curated ``soothe.subagent.*`` progress (IG-339)."""
        text = (line or "").strip()
        if not text:
            return
        self._subagent_notes.append(text)
        try:
            w = self.query_one("#subagent-notes", Static)
        except Exception:  # noqa: BLE001
            return
        w.update("\n".join(self._subagent_notes))
        w.display = True

    def set_running(self) -> None:
        """Mark the tool as running (approved and executing).

        Call this when approval is granted to start the running animation.
        """
        if self._status == "running":
            return  # Already running

        self._status = "running"
        self._start_time = time()
        if self._result_summary_widget:
            self._result_summary_widget.display = False
        if self._status_widget:
            self._status_widget.add_class("pending")
            self._status_widget.display = True
        self._update_running_animation()
        self._animation_timer = self.set_interval(0.1, self._update_running_animation)

    def _update_running_animation(self) -> None:
        """Update the running spinner animation."""
        if self._status != "running" or self._status_widget is None:
            return

        spinner_frames = get_glyphs().spinner_frames
        frame = spinner_frames[self._spinner_position]
        self._spinner_position = (self._spinner_position + 1) % len(spinner_frames)

        elapsed = ""
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
            elapsed = f" ({format_duration(elapsed_secs)})"

        text = f"{frame} Running...{elapsed}"
        self._status_widget.update(Content.styled(text, theme.get_theme_colors(self).warning))

    def _stop_animation(self) -> None:
        """Stop the running animation."""
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def _duration_ms_since_start(self) -> int:
        if self._start_time is None:
            return 0
        return int((time() - self._start_time) * 1000)

    def _apply_result_summary(self, line: str, *, is_error: bool) -> None:
        """Show the CLI-style ✓/✗ result line under the command header."""
        w = self._result_summary_widget
        if w is None:
            return
        w.remove_class("success")
        w.remove_class("error")
        w.add_class("error" if is_error else "success")
        w.update(Content(line))
        w.display = True

    def set_success(self, result: str = "") -> None:
        """Mark the tool call as successful.

        Args:
            result: Tool output/result to display
        """
        self._stop_animation()
        self._status = "success"
        self._output = _strip_success_exit_line(result)
        self._expanded = False
        duration_ms = self._duration_ms_since_start()
        line = _TOOL_CARD_PRESENTATION.format_tool_result_status_line(
            self._tool_name,
            self._output,
            is_error=False,
            duration_ms=duration_ms,
        )
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.display = False
        self._apply_result_summary(line, is_error=False)
        self._update_output_display()

    def set_error(self, error: str) -> None:
        """Mark the tool call as failed.

        Args:
            error: Error message
        """
        self._stop_animation()
        self._status = "error"
        command = (
            self._args.get("command") if self._tool_name in {"shell", "bash", "execute"} else None
        )
        if command and isinstance(command, str) and command.strip():
            self._output = f"$ {command}\n\n{error}"
        else:
            self._output = error
        self._expanded = False
        duration_ms = self._duration_ms_since_start()
        line = _TOOL_CARD_PRESENTATION.format_tool_result_status_line(
            self._tool_name,
            error,
            is_error=True,
            duration_ms=duration_ms,
        )
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.remove_class("error")
            self._status_widget.display = False
        self._apply_result_summary(line, is_error=True)
        self._update_output_display()

    def set_rejected(self) -> None:
        """Mark the tool call as rejected by user."""
        self._stop_animation()
        self._status = "rejected"
        if self._result_summary_widget:
            self._result_summary_widget.display = False
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.add_class("rejected")
            error_icon = get_glyphs().error
            text = f"{error_icon} Rejected"
            colors = theme.get_theme_colors(self)
            self._status_widget.update(Content.styled(text, colors.warning))
            self._status_widget.display = True

    def set_skipped(self) -> None:
        """Mark the tool call as skipped (due to another rejection)."""
        self._stop_animation()
        self._status = "skipped"
        if self._result_summary_widget:
            self._result_summary_widget.display = False
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.add_class("rejected")  # Use same styling as rejected
            self._status_widget.update(Content.styled("- Skipped", "dim"))
            self._status_widget.display = True

    def toggle_output(self) -> None:
        """Toggle between preview and full output display."""
        out = (self._output or "").strip()
        if not out and self._status != "success":
            return
        self._expanded = not self._expanded
        self._update_output_display()

    def on_click(self, event: Click) -> None:
        """Toggle output expansion, or show timestamp if no output."""
        event.stop()  # Prevent click from bubbling up and scrolling
        out = (self._output or "").strip()
        if out or self._status == "success":
            self.toggle_output()
        else:
            _show_timestamp_toast(self)

    def _format_output(self, output: str, *, is_preview: bool = False) -> FormattedOutput:
        """Format tool output based on tool type for nicer display.

        Args:
            output: Raw output string
            is_preview: Whether this is for preview (truncated) display

        Returns:
            FormattedOutput with content and optional truncation info.
        """
        output = output.strip()
        if not output:
            return FormattedOutput(content=Content(""))

        # Tool-specific formatting using dispatch table
        formatters = {
            "write_todos": self._format_todos_output,
            "ls": self._format_ls_output,
            "list_files": self._format_ls_output,
            "read_file": self._format_file_output,
            "write_file": self._format_file_output,
            "edit_file": self._format_file_output,
            "grep": self._format_search_output,
            "glob": self._format_search_output,
            "shell": self._format_shell_output,
            "bash": self._format_shell_output,
            "execute": self._format_shell_output,
            "web_search": self._format_web_output,
            "fetch_url": self._format_web_output,
            "search_web": self._format_web_output,
            "crawl_web": self._format_web_output,
            "task": self._format_task_output,
        }

        formatter = formatters.get(self._tool_name)
        if formatter:
            return formatter(output, is_preview=is_preview)

        if is_preview:
            # Fallback for unknown tools: use generic truncation
            lines = output.split("\n")
            if len(lines) > self._PREVIEW_LINES:
                return self._format_lines_output(lines, is_preview=True)
            if len(output) > self._PREVIEW_CHARS:
                truncated = output[: self._PREVIEW_CHARS]
                truncation = f"{len(output) - self._PREVIEW_CHARS} more chars"
                return FormattedOutput(content=Content(truncated), truncation=truncation)

        # Default: plain text (Content treats input as literal)
        return FormattedOutput(content=Content(output))

    def _prefix_output(self, content: Content) -> Content:  # noqa: PLR6301  # Grouped as method for widget cohesion
        """Prefix output with output marker and indent continuation lines.

        Args:
            content: The styled output content to prefix and indent.

        Returns:
            `Content` with output prefix on first line and indented
                continuation.
        """
        if not content.plain:
            return Content("")
        output_prefix = get_glyphs().output_prefix
        lines = content.split("\n")
        prefixed = [Content.assemble(f"{output_prefix} ", lines[0])]
        prefixed.extend(Content.assemble("  ", line) for line in lines[1:])
        return Content("\n").join(prefixed)

    def _format_todos_output(self, output: str, *, is_preview: bool = False) -> FormattedOutput:
        """Format write_todos output as a checklist.

        Returns:
            FormattedOutput with checklist content and optional truncation info.
        """
        items = self._parse_todo_items(output)
        if items is None:
            return FormattedOutput(content=Content(output))

        if not items:
            return FormattedOutput(content=Content.styled("    No todos", "dim"))

        lines: list[Content] = []
        max_items = TOOL_CARD_PREVIEW_TODO_ITEMS if is_preview else len(items)

        # Build stats header
        stats = self._build_todo_stats(items)
        if stats:
            lines.extend([Content.assemble("    ", stats), Content("")])

        # Format each item
        lines.extend(self._format_single_todo(item) for item in items[:max_items])

        truncation = None
        if is_preview and len(items) > max_items:
            truncation = f"{len(items) - max_items} more"

        return FormattedOutput(content=Content("\n").join(lines), truncation=truncation)

    def _parse_todo_items(self, output: str) -> list | None:  # noqa: PLR6301  # Grouped as method for widget cohesion
        """Parse todo items from output.

        Returns:
            List of todo items, or None if parsing fails.
        """
        list_match = re.search(r"\[(\{.*\})\]", output.replace("\n", " "), re.DOTALL)
        if list_match:
            try:
                return ast.literal_eval("[" + list_match.group(1) + "]")
            except (ValueError, SyntaxError):
                return None
        try:
            items = ast.literal_eval(output)
            return items if isinstance(items, list) else None
        except (ValueError, SyntaxError):
            return None

    def _build_todo_stats(self, items: list) -> Content:
        """Build stats content for todo list.

        Returns:
            Styled `Content` showing active, pending, and completed counts.
        """
        colors = theme.get_theme_colors(self)
        completed = sum(1 for i in items if isinstance(i, dict) and i.get("status") == "completed")
        active = sum(1 for i in items if isinstance(i, dict) and i.get("status") == "in_progress")
        pending = len(items) - completed - active

        parts: list[Content] = []
        if active:
            parts.append(Content.styled(f"{active} active", colors.warning))
        if pending:
            parts.append(Content.styled(f"{pending} pending", "dim"))
        if completed:
            parts.append(Content.styled(f"{completed} done", colors.success))
        return Content.styled(" | ", "dim").join(parts) if parts else Content("")

    def _format_single_todo(self, item: dict | str) -> Content:
        """Format a single todo item.

        Returns:
            Styled `Content` with checkbox and status styling.
        """
        colors = theme.get_theme_colors(self)
        if isinstance(item, dict):
            text = item.get("content", str(item))
            status = item.get("status", "pending")
        else:
            text = str(item)
            status = "pending"

        if len(text) > _MAX_TODO_CONTENT_LEN:
            text = text[: _MAX_TODO_CONTENT_LEN - 3] + "..."

        glyphs = get_glyphs()
        if status == "completed":
            return Content.assemble(
                Content.styled(f"    {glyphs.checkmark} done", colors.success),
                Content.styled(f"   {text}", "dim"),
            )
        if status == "in_progress":
            return Content.assemble(
                Content.styled(f"    {glyphs.circle_filled} active", colors.warning),
                f" {text}",
            )
        return Content.assemble(
            Content.styled(f"    {glyphs.circle_empty} todo", "dim"),
            f"   {text}",
        )

    def _format_ls_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, output: str, *, is_preview: bool = False
    ) -> FormattedOutput:
        """Format ls output as a clean directory listing.

        Returns:
            FormattedOutput with directory listing and optional truncation info.
        """
        # Try to parse as a Python list (common format)
        try:
            items = ast.literal_eval(output)
            if isinstance(items, list):
                lines: list[Content] = []
                max_items = self._PREVIEW_LINES if is_preview else len(items)
                for item in items[:max_items]:
                    path = Path(str(item))
                    name = path.name
                    if path.suffix in {".py", ".pyx"}:
                        lines.append(Content.styled(f"    {name}", theme.FILE_PYTHON))
                    elif path.suffix in {".json", ".yaml", ".yml", ".yaml"}:
                        lines.append(Content.styled(f"    {name}", theme.FILE_CONFIG))
                    elif not path.suffix:
                        lines.append(Content.styled(f"    {name}/", theme.FILE_DIR))
                    else:
                        lines.append(Content(f"    {name}"))

                truncation = None
                if is_preview and len(items) > max_items:
                    truncation = f"{len(items) - max_items} more"

                return FormattedOutput(content=Content("\n").join(lines), truncation=truncation)
        except (ValueError, SyntaxError):
            pass

        # Fallback: line-based output with preview truncation
        lines = output.split("\n")
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)
        parts = [
            Content(f"    {raw_line.strip()}") for raw_line in lines[:max_lines] if raw_line.strip()
        ]

        content = Content("\n").join(parts) if parts else Content("")
        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more"

        return FormattedOutput(content=content, truncation=truncation)

    def _format_file_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, output: str, *, is_preview: bool = False
    ) -> FormattedOutput:
        """Format file read/write output.

        Returns:
            FormattedOutput with file content and optional truncation info.
        """
        lines = output.split("\n")
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)

        parts = [Content(line) for line in lines[:max_lines]]
        content = Content("\n").join(parts)

        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more lines"

        return FormattedOutput(content=content, truncation=truncation)

    def _format_search_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, output: str, *, is_preview: bool = False
    ) -> FormattedOutput:
        """Format grep/glob search output.

        Returns:
            FormattedOutput with search results and optional truncation info.
        """
        # Try to parse as a Python list (glob returns list of paths)
        try:
            items = ast.literal_eval(output.strip())
            if isinstance(items, list):
                parts: list[Content] = []
                max_items = self._PREVIEW_LINES if is_preview else len(items)
                for item in items[:max_items]:
                    path = Path(str(item))
                    try:
                        rel = path.relative_to(Path.cwd())
                        display = str(rel)
                    except ValueError:
                        display = path.name
                    parts.append(Content(f"    {display}"))

                truncation = None
                if is_preview and len(items) > max_items:
                    truncation = f"{len(items) - max_items} more files"

                return FormattedOutput(content=Content("\n").join(parts), truncation=truncation)
        except (ValueError, SyntaxError):
            pass

        # Fallback: line-based output (grep results)
        lines = output.split("\n")
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)

        parts = [
            Content(f"    {raw_line.strip()}") for raw_line in lines[:max_lines] if raw_line.strip()
        ]

        content = Content("\n").join(parts) if parts else Content("")
        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more"

        return FormattedOutput(content=content, truncation=truncation)

    def _format_shell_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, output: str, *, is_preview: bool = False
    ) -> FormattedOutput:
        """Format shell command output.

        Returns:
            FormattedOutput with shell output and optional truncation info.
        """
        lines = output.split("\n")
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)

        parts: list[Content] = []
        for i, line in enumerate(lines[:max_lines]):
            if i == 0 and line.startswith("$ "):
                parts.append(Content.styled(line, "dim"))
            else:
                parts.append(Content(line))

        content = Content("\n").join(parts) if parts else Content("")

        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more lines"

        return FormattedOutput(content=content, truncation=truncation)

    def _format_web_output(self, output: str, *, is_preview: bool = False) -> FormattedOutput:
        """Format web_search/fetch_url/search_web/crawl_web output.

        Returns:
            FormattedOutput with web response and optional truncation info.
        """
        data = self._try_parse_web_data(output)
        if isinstance(data, dict):
            return self._format_web_dict(data, is_preview=is_preview)

        # Fallback: plain text
        return self._format_lines_output(output.split("\n"), is_preview=is_preview)

    @staticmethod
    def _try_parse_web_data(output: str) -> dict | None:
        """Try to parse web output as JSON or dict.

        Returns:
            Parsed dict if successful, None otherwise.
        """
        try:
            if output.strip().startswith("{"):
                return json.loads(output)
            return ast.literal_eval(output)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            return None

    def _format_web_dict(self, data: dict, *, is_preview: bool) -> FormattedOutput:
        """Format a parsed web response dict.

        Returns:
            FormattedOutput with web response content and optional truncation info.
        """
        # Handle search results
        if "results" in data:
            return self._format_web_search_results(data.get("results", []), is_preview=is_preview)

        # Handle URL crawl response
        if "markdown_content" in data:
            lines = data["markdown_content"].split("\n")
            return self._format_lines_output(lines, is_preview=is_preview)

        # Generic dict - show key fields
        parts: list[Content] = []
        max_keys = TOOL_CARD_PREVIEW_WEB_DICT_KEYS if is_preview else len(data)
        for k, v in list(data.items())[:max_keys]:
            v_str = str(v)
            if is_preview and len(v_str) > _MAX_WEB_CONTENT_LEN:
                v_str = v_str[:_MAX_WEB_CONTENT_LEN] + "..."
            parts.append(Content(f"  {k}: {v_str}"))
        truncation = None
        if is_preview and len(data) > max_keys:
            truncation = f"{len(data) - max_keys} more"
        return FormattedOutput(
            content=Content("\n").join(parts) if parts else Content(""),
            truncation=truncation,
        )

    def _format_web_search_results(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, results: list, *, is_preview: bool
    ) -> FormattedOutput:
        """Format web search results.

        Returns:
            FormattedOutput with search results and optional truncation info.
        """
        if not results:
            return FormattedOutput(content=Content.styled("No results", "dim"))
        if is_preview:
            title = results[0].get("title", "")
            parts = [Content.styled(f"  {title}", "bold")]
            truncation = f"{len(results) - 1} more results" if len(results) > 1 else None
            return FormattedOutput(content=Content("\n").join(parts), truncation=truncation)

        parts: list[Content] = []
        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            parts.extend(
                [
                    Content.styled(f"  {title}", "bold"),
                    Content.styled(f"  {url}", "dim"),
                ]
            )
        return FormattedOutput(content=Content("\n").join(parts), truncation=None)

    def _format_lines_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, lines: list[str], *, is_preview: bool
    ) -> FormattedOutput:
        """Format a list of lines with optional preview truncation.

        Returns:
            FormattedOutput with lines content and optional truncation info.
        """
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)
        parts = [Content(line) for line in lines[:max_lines]]
        content = Content("\n").join(parts) if parts else Content("")
        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more lines"
        return FormattedOutput(content=content, truncation=truncation)

    def _format_task_output(  # noqa: PLR6301  # Grouped as method for widget cohesion
        self, output: str, *, is_preview: bool = False
    ) -> FormattedOutput:
        """Format task (subagent) output.

        Returns:
            FormattedOutput with task output and optional truncation info.
        """
        lines = output.split("\n")
        max_lines = self._PREVIEW_LINES if is_preview else len(lines)

        parts = [Content(line) for line in lines[:max_lines]]
        content = Content("\n").join(parts) if parts else Content("")

        truncation = None
        if is_preview and len(lines) > max_lines:
            truncation = f"{len(lines) - max_lines} more lines"

        return FormattedOutput(content=content, truncation=truncation)

    def _cli_result_summary_active(self) -> bool:
        """True when the Done/Failed summary row is shown (IG-320)."""
        w = self._result_summary_widget
        return self._status in ("success", "error") and w is not None and bool(w.display)

    def _update_output_display(self) -> None:
        """Update the output display based on expanded state."""
        if not self._preview_widget or not self._full_widget or not self._hint_widget:
            return

        output_stripped = (self._output or "").strip()
        empty_success = self._status == "success" and not output_stripped

        def _empty_success_content() -> Content:
            return self._prefix_output(Content.styled("(no tool output)", "dim italic"))

        if self._cli_result_summary_active():
            if not self._expanded:
                self._preview_widget.display = False
                self._full_widget.display = False
                if output_stripped:
                    self._hint_widget.update(
                        Content.styled("click or Ctrl+O to show full output", "dim italic")
                    )
                    self._hint_widget.display = True
                else:
                    self._hint_widget.display = False
                return

            self._preview_widget.display = False
            if empty_success:
                self._full_widget.update(_empty_success_content())
            else:
                result = self._format_output(self._output, is_preview=False)
                prefixed = self._prefix_output(result.content)
                self._full_widget.update(prefixed)
            self._full_widget.display = True
            self._hint_widget.update(Content.styled("click or Ctrl+O to collapse", "dim italic"))
            self._hint_widget.display = True
            return

        lines = output_stripped.split("\n")
        total_lines = len(lines)
        total_chars = len(output_stripped)

        needs_truncation = (not empty_success) and (
            total_lines > self._PREVIEW_LINES or total_chars > self._PREVIEW_CHARS
        )

        if self._expanded:
            self._preview_widget.display = False
            if empty_success:
                self._full_widget.update(_empty_success_content())
            else:
                result = self._format_output(self._output, is_preview=False)
                prefixed = self._prefix_output(result.content)
                self._full_widget.update(prefixed)
            self._full_widget.display = True
            self._hint_widget.update(Content.styled("click or Ctrl+O to collapse", "dim italic"))
            self._hint_widget.display = True
        else:
            self._full_widget.display = False
            if empty_success:
                self._preview_widget.update(_empty_success_content())
                self._preview_widget.display = True
                self._hint_widget.display = False
            elif needs_truncation:
                result = self._format_output(self._output, is_preview=True)
                prefixed = self._prefix_output(result.content)
                self._preview_widget.update(prefixed)
                self._preview_widget.display = True

                if result.truncation:
                    ellipsis = get_glyphs().ellipsis
                    hint = Content.styled(
                        f"{ellipsis} {result.truncation} — click or Ctrl+O to expand",
                        "dim",
                    )
                else:
                    hint = Content.styled("click or Ctrl+O to expand", "dim italic")
                self._hint_widget.update(hint)
                self._hint_widget.display = True
            elif output_stripped:
                result = self._format_output(output_stripped, is_preview=False)
                prefixed = self._prefix_output(result.content)
                self._preview_widget.update(prefixed)
                self._preview_widget.display = True
                self._hint_widget.display = False
            else:
                self._preview_widget.display = False
                self._hint_widget.display = False

    @property
    def has_output(self) -> bool:
        """Check if this tool message has output to display.

        Returns:
            True if there is output content, False otherwise.
        """
        if (self._output or "").strip():
            return True
        return self._status == "success"


class DiffMessage(_TimestampClickMixin, Static):
    """Widget displaying a diff with syntax highlighting."""

    can_select = True
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

    def __init__(self, diff_content: str, file_path: str = "", **kwargs: Any) -> None:
        """Initialize a diff message.

        Args:
            diff_content: The unified diff content
            file_path: Path to the file being modified
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._diff_content = diff_content
        self._file_path = file_path

    def compose(self) -> ComposeResult:
        """Compose the diff message layout.

        Yields:
            Widgets displaying the diff header and formatted content.
        """
        if self._file_path:
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
    """One tool invocation row on the step card (IG-402)."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    phase: str  # pending | running | success | error | rejected | skipped
    output: str = ""
    duration_ms: int = 0
    started_at: float | None = None


class CognitionStepMessage(Vertical):
    """Agent-loop act step card: aggregates main-agent tool calls (IG-402).

    Header shows per-tool counts; body lists one CLI-style row per call. Click
    toggles expansion when there are more than ``_STEP_TOOL_PREVIEW_ROWS`` rows.
    """

    can_select = True

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
        color: $cognition;
        text-style: bold;
    }

    CognitionStepMessage .step-status {
        margin-left: 3;
    }

    CognitionStepMessage .step-status.pending {
        color: $warning;
    }

    CognitionStepMessage .step-tools {
        margin-left: 3;
        margin-top: 0;
        height: auto;
        color: $text;
    }

    CognitionStepMessage .step-tools-hint {
        margin-left: 3;
        color: $text-muted;
        background: transparent;
        height: auto;
    }

    CognitionStepMessage .step-subagent-notes {
        margin-left: 3;
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
        raw = description.strip()
        if len(raw) > TOOL_CARD_PREVIEW_CHARS:
            raw = raw[: TOOL_CARD_PREVIEW_CHARS - 3].rstrip() + "..."
        self._description = raw
        self._status = "pending"  # pending | running | success | error
        self._spinner_position = 0
        self._start_time: float | None = None
        self._animation_timer: Timer | None = None
        self._status_widget: Static | None = None
        self._header_widget: Static | None = None
        self._tools_widget: Static | None = None
        self._tools_hint_widget: Static | None = None
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

    def compose(self) -> ComposeResult:
        prefix = get_glyphs().tool_prefix
        header = f"{prefix} Step · {self._description}"
        yield Static(header, markup=False, classes="step-header", id="step-cognition-header")
        yield Static("", classes="step-status", id="step-cognition-status")
        yield Static("", classes="step-tools", id="step-cognition-tools", markup=False)
        yield Static("", classes="step-tools-hint", id="step-cognition-tools-hint", markup=False)
        yield Static(
            "",
            markup=False,
            classes="step-subagent-notes",
            id="step-cognition-subagent-notes",
        )
        yield Static("", classes="step-detail", id="step-cognition-detail")

    def on_mount(self) -> None:
        self._header_widget = self.query_one("#step-cognition-header", Static)
        self._status_widget = self.query_one("#step-cognition-status", Static)
        self._tools_widget = self.query_one("#step-cognition-tools", Static)
        self._tools_hint_widget = self.query_one("#step-cognition-tools-hint", Static)
        self._detail_widget = self.query_one("#step-cognition-detail", Static)
        notes = self.query_one("#step-cognition-subagent-notes", Static)
        notes.display = False
        self._status_widget.display = False
        self._tools_widget.display = False
        self._tools_hint_widget.display = False
        self._detail_widget.display = False
        self._refresh_header_title()
        self._refresh_tools_display()
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

    def on_click(self, event: Click) -> None:  # noqa: ARG002
        """Toggle tool list collapse or show timestamp when there are no tools."""
        event.stop()
        if self._rows and len(self._rows) > _STEP_TOOL_PREVIEW_ROWS:
            self._tools_body_collapsed = not self._tools_body_collapsed
            self._refresh_tools_display()
        else:
            _show_timestamp_toast(self)

    def append_subagent_activity(self, line: str) -> None:
        """Append one metadata line (task subgraph tools, wire events, same as tool card)."""
        text = (line or "").strip()
        if not text:
            return
        self._subagent_notes.append(text)
        try:
            w = self.query_one("#step-cognition-subagent-notes", Static)
        except Exception:  # noqa: BLE001
            return
        w.update("\n".join(self._subagent_notes))
        w.display = True

    def _bump_stat(self, tool_name: str) -> None:
        key = get_tool_display_name(_normalize_tool_name_for_arg_map(tool_name or ""))
        if key not in self._stats_counts:
            self._stats_order.append(key)
            self._stats_counts[key] = 0
        self._stats_counts[key] += 1

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

    def _refresh_header_title(self) -> None:
        if self._header_widget is None:
            return
        prefix = get_glyphs().tool_prefix
        self._header_widget.update(
            f"{prefix} Step · {self._description}{self._stats_title_suffix()}"
        )

    def _row_to_content(self, row: _StepToolRow) -> Content:
        phase = row.phase
        elapsed: float | None = None
        if phase == "running" and row.started_at is not None:
            elapsed = max(0.0, time() - row.started_at)
        spin = None
        if phase == "running":
            frames = get_glyphs().spinner_frames
            spin = frames[self._spinner_position % len(frames)]
        return format_tool_call_row(
            row.tool_name,
            row.args,
            phase=phase,
            output=row.output,
            duration_ms=row.duration_ms,
            running_spinner=spin,
            running_elapsed_secs=elapsed,
        )

    def _refresh_tools_display(self) -> None:
        if self._tools_widget is None or self._tools_hint_widget is None:
            return
        if not self._rows:
            self._tools_widget.display = False
            self._tools_hint_widget.display = False
            return
        self._tools_widget.display = True
        show_all = len(self._rows) <= _STEP_TOOL_PREVIEW_ROWS or not self._tools_body_collapsed
        visible = self._rows if show_all else self._rows[:_STEP_TOOL_PREVIEW_ROWS]
        lines = [self._row_to_content(r) for r in visible]
        self._tools_widget.update(Content("\n").join(lines))
        remaining = len(self._rows) - len(visible)
        if remaining > 0:
            ellipsis = get_glyphs().ellipsis
            self._tools_hint_widget.update(
                Content.styled(
                    f"{ellipsis} {remaining} more tool call(s) — click to expand",
                    "dim",
                )
            )
            self._tools_hint_widget.display = not show_all
        elif len(self._rows) > _STEP_TOOL_PREVIEW_ROWS and show_all:
            self._tools_hint_widget.update(
                Content.styled(f"{get_glyphs().ellipsis} click to collapse", "dim italic")
            )
            self._tools_hint_widget.display = True
        else:
            self._tools_hint_widget.display = False

    def add_tool_call(self, tool_call_id: str, tool_name: str, args: dict[str, Any]) -> None:
        """Register a new tool row (pending)."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return
        if tcid in self._row_index:
            self.update_tool_args(tcid, args)
            return
        row = _StepToolRow(
            tool_call_id=tcid,
            tool_name=(tool_name or "tool").strip() or "tool",
            args=dict(args or {}),
            phase="pending",
        )
        self._rows.append(row)
        self._row_index[tcid] = row
        self._bump_stat(row.tool_name)
        self._refresh_header_title()
        self._refresh_tools_display()

    def has_tool_call_row(self, tool_call_id: str) -> bool:
        """Return True if this step card already tracks ``tool_call_id``."""
        return str(tool_call_id) in self._row_index

    def row_duration_ms_since_started(self, tool_call_id: str) -> int:
        """Elapsed ms since this row entered running state (for result lines)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.started_at is None:
            return 0
        return int((time() - row.started_at) * 1000)

    def update_tool_args(self, tool_call_id: str, args: dict[str, Any]) -> None:
        """Refresh kwargs when streaming fills in arguments."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.args = dict(args or {})
        self._refresh_tools_display()

    def set_tool_running(self, tool_call_id: str) -> None:
        """Mark a tool row as executing (after approval)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.phase not in ("pending", "running"):
            return
        row.phase = "running"
        row.started_at = time()
        self._refresh_tools_display()

    def set_tool_success(self, tool_call_id: str, result: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as success."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "success"
        row.output = _strip_success_exit_line(result)
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_tools_display()

    def set_tool_error(self, tool_call_id: str, error: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as error."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "error"
        row.output = error
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_tools_display()

    def set_tool_rejected(self, tool_call_id: str) -> None:
        """Mark a tool row as rejected (HITL)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "rejected"
        row.started_at = None
        self._refresh_tools_display()

    def set_tool_skipped(self, tool_call_id: str) -> None:
        """Mark a tool row skipped (batch reject / incomplete)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "skipped"
        row.started_at = None
        self._refresh_tools_display()

    def mark_unfinished_tools_skipped(self) -> None:
        """Mark pending/running rows skipped when the step ends without results."""
        for row in self._rows:
            if row.phase in ("pending", "running"):
                row.phase = "skipped"
                row.started_at = None
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
            row = _StepToolRow(
                tool_call_id=tcid,
                tool_name=name,
                args=dict(args),
                phase=phase,
                output=str(raw.get("output", "") or ""),
                duration_ms=int(raw.get("duration_ms", 0) or 0),
                started_at=raw.get("started_at"),
            )
            self._rows.append(row)
            self._row_index[tcid] = row
            self._bump_stat(name)
        self._refresh_header_title()
        self._refresh_tools_display()

    def set_running(self) -> None:
        """Show animated running state (call after mount)."""
        if self._status == "running":
            return
        self._status = "running"
        self._start_time = time()
        self._tools_body_collapsed = False
        if self._status_widget:
            self._status_widget.add_class("pending")
            self._status_widget.display = True
        self._update_running_animation()
        self._animation_timer = self.set_interval(0.1, self._update_running_animation)

    def _stop_animation(self) -> None:
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def _update_running_animation(self) -> None:
        if self._status != "running" or self._status_widget is None:
            return
        frames = get_glyphs().spinner_frames
        frame = frames[self._spinner_position]
        self._spinner_position = (self._spinner_position + 1) % len(frames)
        elapsed = ""
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        colors = theme.get_theme_colors(self)
        self._status_widget.update(Content.styled(f"{frame} Running...{elapsed}", colors.warning))
        if any(r.phase == "running" for r in self._rows):
            self._refresh_tools_display()

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
        self._refresh_tools_display()

        duration_s = duration_ms / 1000.0
        dur_str = f"{duration_s:.1f}s"
        tool_part = f" · {tool_call_count} tools" if tool_call_count > 0 else ""

        if success:
            if self._status_widget:
                self._status_widget.remove_class("pending")
                self._status_widget.display = False
            detail = f"Done · {dur_str}{tool_part}"
            if summary.strip() and summary.strip() not in ("Done",):
                detail = f"{detail}\n{summary.strip()}"
            self._detail_widget.update(Content.styled(detail, "dim"))
            self._detail_widget.display = True
            return

        err_text = summary.strip() or "Step failed"
        colors = theme.get_theme_colors(self)
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.add_class("error")
            icon = get_glyphs().error
            self._status_widget.update(Content.styled(f"{icon} Failed · {dur_str}", colors.error))
            self._status_widget.display = True
        self._detail_widget.update(Content(err_text))
        self._detail_widget.display = True

    def set_interrupted(self, message: str) -> None:
        """Mark step as aborted (stream error / cancel) while still running."""
        self._stop_animation()
        self._status = "error"
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


class CognitionPlanReasonMessage(_TimestampClickMixin, Vertical):
    """Single card for plan assessment, plan reasoning, and next action (keep/new)."""

    can_select = True

    DEFAULT_CSS = """
    CognitionPlanReasonMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionPlanReasonMessage .cognition-plan-header {
        height: auto;
        margin: 0;
        color: $text-muted;
        text-style: bold;
    }

    CognitionPlanReasonMessage .plan-section-line {
        height: auto;
        margin-left: 3;
        color: $text-muted;
    }

    CognitionPlanReasonMessage:hover {
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
        self._plan_action = plan_action if plan_action in ("keep", "new") else "new"
        self._assessment_reasoning = assessment_reasoning.strip()
        self._plan_reasoning = plan_reasoning.strip()

    def compose(self) -> ComposeResult:
        prefix = get_glyphs().tool_prefix
        badge = f" [{self._plan_action}]" if self._plan_action in ("keep", "new") else ""
        args = f"{self._next_action}{badge}"
        header = f"{prefix} Plan({args})"
        yield Static(Content.styled(header, "bold dim"), classes="cognition-plan-header")

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
    """Two-level Goal → steps tree; one aggregate block updates in place."""

    can_select = True

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
        color: $text-muted;
        text-style: bold;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-steps {
        height: auto;
        margin: 0;
        color: $text-muted;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-footer {
        height: auto;
        margin: 0;
        color: $text-muted;
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
        self._steps_static: Static | None = None

    @staticmethod
    def _clip(text: str, max_len: int) -> str:
        t = (text or "").strip().replace("\n", " ")
        if len(t) <= max_len:
            return t
        return t[: max_len - 1].rstrip() + "…"

    def _goal_header_content(self) -> Content:
        prefix = get_glyphs().tool_prefix
        g = self._clip(self._goal_text, _MAX_GOAL_HEADER)
        args = g
        if self._max_iterations > 1:
            args += f", iter<={self._max_iterations}"
        line = f"{prefix} Goal({args})"
        return Content.styled(line, "bold dim")

    def _indent_prefix(self) -> str:
        g = get_glyphs()
        return f"{g.output_prefix} "

    def _format_step_line(self, st: _StepLineState) -> str:
        g = get_glyphs()
        body = self._clip(st.description, _MAX_GOAL_STEP_DESC)
        if st.phase == "running":
            return f"{self._indent_prefix()}{g.circle_empty} {body}"
        icon = g.checkmark if st.success else g.error
        dur_s = max(0.001, st.duration_ms / 1000.0)
        dur = format_duration(dur_s)
        line = f"{self._indent_prefix()}{icon} {body} · {dur}"
        if st.tool_call_count > 0:
            line += f" · {st.tool_call_count} tools"
        tail = (st.summary or "").strip()
        if tail and tail not in ("Done", "Failed"):
            line += f" — {self._clip(tail, 80)}"
        return line

    def _refresh_steps_display(self) -> None:
        if self._steps_static is None:
            return
        lines = [
            self._format_step_line(self._steps[sid])
            for sid in self._step_order
            if sid in self._steps
        ]
        text = "\n".join(lines)
        self._steps_static.update(Content.styled(text, "dim") if text else Content(""))

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
                ft.update(Content.styled(self._footer_plain, "dim"))
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
        }

    def _apply_snapshot(self, snap: dict[str, Any]) -> None:
        """Restore in-memory goal tree state from :meth:`snapshot_dict` output."""
        self._goal_text = str(snap.get("goal", self._goal_text))
        self._max_iterations = int(snap.get("max_iterations", self._max_iterations))
        self._footer_plain = str(snap.get("footer_text", ""))
        self._footer_visible = bool(snap.get("footer_visible", False))
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
        pct_display = progress_map.get(goal_progress, "0%")
        parts: list[str] = [str(status or "done"), pct_display]
        if total_steps:
            parts.append(f"{total_steps} step(s)")
        cs = (completion_summary or "").strip()
        if cs:
            parts.append(self._clip(cs, 100))
        self._footer_plain = " · ".join(parts)
        self._footer_visible = True
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(Content.styled(self._footer_plain, "dim"))
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
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(Content.styled(self._footer_plain, "dim"))
            footer.display = True
        except Exception:
            pass


class ErrorMessage(_TimestampClickMixin, Static):
    """Widget displaying an error message."""

    can_select = True
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

    can_select = True
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
