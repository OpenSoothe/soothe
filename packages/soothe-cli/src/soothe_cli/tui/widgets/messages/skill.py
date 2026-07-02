"""Skill message widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import on
from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.reactive import var
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs, is_ascii_mode
from soothe_cli.tui.markdown_theme import build_markdown
from soothe_cli.tui.preview_limits import SKILL_CARD_PREVIEW_CHARS, SKILL_CARD_PREVIEW_LINES

if TYPE_CHECKING:
    from textual.app import ComposeResult


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


def _build_skill_description_preview(
    description: str,
    *,
    max_lines: int,
    max_chars: int,
    ellipsis: str,
) -> tuple[str, bool]:
    """Return collapsed description preview and truncation flag."""
    text = description.strip()
    if not text:
        return "", False

    lines = text.splitlines()
    by_lines = len(lines) > max_lines
    by_chars = len(text) > max_chars
    if not by_lines and not by_chars:
        return text, False

    preview_lines = lines[:max_lines]
    preview = "\n".join(preview_lines).strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip()
    if not preview:
        return f"{ellipsis}", True
    if not preview.endswith(ellipsis):
        preview = f"{preview}{ellipsis}"
    return preview, True


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
        self._description_widget: _SkillToggle | None = None
        self._description_preview = description.strip()
        self._description_needs_truncation = False
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
                id="skill-description",
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
        if self._description:
            self._description_widget = self.query_one("#skill-description", _SkillToggle)
            self._description_preview, self._description_needs_truncation = (
                _build_skill_description_preview(
                    self._description,
                    max_lines=self._PREVIEW_LINES,
                    max_chars=self._PREVIEW_CHARS,
                    ellipsis=get_glyphs().ellipsis,
                )
            )
            self._render_description(expanded=self._expanded)

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

        if needs_truncation and self._hint_widget:
            self._hint_widget.display = False
        else:
            # Short body — show fully rendered, no preview needed.
            self._ensure_md_rendered(body)
            if not self._description_needs_truncation:
                self._expanded = True

    def _render_description(self, *, expanded: bool) -> None:
        """Render description as preview or full text based on expansion state."""
        if not self._description_widget:
            return
        if expanded or not self._description_needs_truncation:
            text = self._description.strip()
        else:
            text = self._description_preview
        self._description_widget.update(Content.styled(text, "dim"))

    def _has_expandable_content(self) -> bool:
        """Return whether skill card has any truncatable/expandable content."""
        return bool(self._stripped_body.strip()) or self._description_needs_truncation

    def _ensure_md_rendered(self, body: str) -> None:
        """Render markdown into the Static widget on first call, then no-op.

        Args:
            body: Stripped markdown body text.
        """
        if self._md_rendered or not self._md_widget:
            return
        try:
            self._md_widget.update(build_markdown(body, self))
        except Exception:
            self._md_widget.update(body)
        self._md_rendered = True

    def toggle_body(self) -> None:
        """Toggle between preview and full body display."""
        if not self._has_expandable_content():
            return
        self._expanded = not self._expanded

    def watch__expanded(self, expanded: bool) -> None:
        """Lazy-render markdown on first expand; update hint text."""
        self._render_description(expanded=expanded)
        body = self._stripped_body.strip()

        if expanded and body:
            self._ensure_md_rendered(body)

        if not self._hint_widget:
            return
        # Hint row is reserved but hint text is disabled.
        self._hint_widget.display = False

    @on(Click, "_SkillToggle")
    def _on_toggle_click(self, event: Click) -> None:
        """Toggle expansion when header or hint is clicked."""
        event.stop()
        if self._stripped_body.strip():
            self.toggle_body()
