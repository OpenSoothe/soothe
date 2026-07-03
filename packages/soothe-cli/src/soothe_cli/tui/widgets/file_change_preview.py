"""Non-blocking file change preview widgets (write / edit / delete).

Shown when a filesystem tool call is recognized so the user can see what will
change. These widgets are informational only and do not block execution.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import (
    TOOL_APPROVAL_BODY_MAX_LINES,
    TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES,
    TOOL_APPROVAL_PREVIEW_LINES,
    TOOL_APPROVAL_VALUE_PREVIEW_CHARS,
)
from soothe_cli.tui.widgets.clipboard import screen_has_text_selection
from soothe_cli.tui.widgets.diff import DIFF_CODE_GAP, compose_diff_line_list

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from soothe_cli.runtime.state.file_tracker import FileOperationRecord


def _format_stats(additions: int, deletions: int) -> Content:
    """Format addition/deletion stats as styled Content."""
    colors = theme.get_theme_colors()
    parts: list[str | tuple[str, str] | Content] = []
    if additions:
        parts.append((f"+{additions}", colors.success))
    if deletions:
        if parts:
            parts.append(" ")
        parts.append((f"-{deletions}", colors.error))
    return Content.assemble(*parts) if parts else Content("")


def _compact_header(
    file_path: str,
    *,
    action_label: str = "",
    additions: int = 0,
    deletions: int = 0,
    extra: str = "",
) -> Static:
    """Build a single-line header: action, path, optional suffix, and diff stats."""
    parts: list[str | tuple[str, str] | Content] = []
    if action_label:
        parts.append(Content.from_markup("[bold]$label[/bold]  ", label=action_label))
    path_markup = "[bold cyan]$path[/bold cyan]"
    if extra:
        path_markup += "  [dim]$extra[/dim]"
    parts.append(Content.from_markup(path_markup, path=file_path, extra=extra))
    stats = _format_stats(additions, deletions)
    if additions or deletions:
        parts.append("  ")
        parts.append(stats)
    return Static(Content.assemble(*parts), classes="file-change-preview-header")


def _count_diff_stats(diff_lines: list[str], old_string: str, new_string: str) -> tuple[int, int]:
    """Count additions and deletions from diff data."""
    if diff_lines:
        additions = sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )
    else:
        additions = new_string.count("\n") + 1 if new_string else 0
        deletions = old_string.count("\n") + 1 if old_string else 0
    return additions, deletions


class FileChangePreviewWidget(Vertical):
    """Base class for filesystem change preview cards.

    Renders as a single-line summary in the message stream by default. Click to
    expand and show diff or content details (IG-544).
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    FileChangePreviewWidget {
        height: auto;
        padding: 0 1;
        margin: 0;
    }

    FileChangePreviewWidget.-collapsed {
        background: transparent;
        border: none;
        border-left: tall $secondary;
    }

    FileChangePreviewWidget.-expanded {
        background: $surface-darken-1;
        border: solid $secondary;
    }

    FileChangePreviewWidget.-collapsed .file-change-preview-body,
    FileChangePreviewWidget.-collapsed .file-change-preview-section-label,
    FileChangePreviewWidget.-collapsed .file-change-preview-label,
    FileChangePreviewWidget.-collapsed .diff-line-added,
    FileChangePreviewWidget.-collapsed .diff-line-removed,
    FileChangePreviewWidget.-collapsed .diff-context {
        display: none;
    }

    FileChangePreviewWidget .file-change-preview-header {
        height: auto;
        margin: 0;
    }

    FileChangePreviewWidget.-collapsed .file-change-preview-header {
        color: $foreground;
    }
    """

    def __init__(self, data: dict[str, Any], *, action_label: str = "") -> None:
        """Initialize with renderer-built data dict."""
        super().__init__(classes="file-change-preview")
        self.data = data
        self._action_label = action_label.strip()
        self._finalized = False
        self._expanded = False

    def on_mount(self) -> None:
        """Start collapsed so file edits stay one line in the transcript."""
        self._apply_expand_classes()

    def on_click(self, event: Click) -> None:
        """Toggle expanded diff/content view without breaking text selection."""
        event.stop()
        if screen_has_text_selection(self.screen):
            return
        self.toggle_expand()

    @property
    def is_expanded(self) -> bool:
        """Return whether the preview body is visible."""
        return self._expanded

    def toggle_expand(self) -> None:
        """Expand or collapse the preview body."""
        self._expanded = not self._expanded
        self._apply_expand_classes()

    def _apply_expand_classes(self) -> None:
        if self._expanded:
            self.remove_class("-collapsed")
            self.add_class("-expanded")
        else:
            self.add_class("-collapsed")
            self.remove_class("-expanded")

    async def finalize_from_record(self, record: FileOperationRecord) -> None:
        """Replace pending preview content with completed on-disk results."""
        from soothe_cli.runtime.state.file_tracker import file_change_action_label
        from soothe_cli.tui.file_change_renderers import update_preview_data_from_record

        self._action_label = file_change_action_label(record)
        update_preview_data_from_record(self.data, record)
        self._finalized = True
        if not self.is_mounted:
            return
        await self.remove_children()
        await self.mount(*self.compose())
        self._apply_expand_classes()

    def compose(self) -> ComposeResult:  # noqa: PLR6301
        """Default compose — subclasses override."""
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
            )
        yield Static("Change details not available", classes="file-change-preview-body")

    def _yield_compact_header(
        self,
        file_path: str,
        *,
        additions: int = 0,
        deletions: int = 0,
        extra: str = "",
    ) -> ComposeResult:
        """Yield a single-line action + path + stats header."""
        yield _compact_header(
            file_path,
            action_label=self._action_label,
            additions=additions,
            deletions=deletions,
            extra=extra,
        )

    def _render_diff_lines_only(self, diff_lines: list[str]) -> ComposeResult:
        """Render diff lines with gutter bars and line numbers (matching DiffMessage)."""
        yield from compose_diff_line_list(
            diff_lines,
            max_lines=TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES,
        )

    @staticmethod
    def _render_string_lines(text: str, *, is_addition: bool) -> ComposeResult:
        """Render string content with gutter bars and line numbers."""
        colors = theme.get_theme_colors()
        glyphs = get_glyphs()
        lines = text.split("\n")
        total_lines = len(lines)
        width = max(3, len(str(total_lines)))
        cls = "diff-line-added" if is_addition else "diff-line-removed"
        gutter_color = colors.success if is_addition else colors.error

        for i, line in enumerate(lines[:TOOL_APPROVAL_PREVIEW_LINES], start=1):
            yield Static(
                Content.assemble(
                    (f"{glyphs.gutter_bar}{i:>{width}}", f"{gutter_color} bold"),
                    f"{DIFF_CODE_GAP}{line}",
                ),
                classes=cls,
            )
        if len(lines) > TOOL_APPROVAL_PREVIEW_LINES:
            remaining = len(lines) - TOOL_APPROVAL_PREVIEW_LINES
            yield Static(Content.styled(f"... ({remaining} more lines)", "dim"))


class WriteFilePreviewWidget(FileChangePreviewWidget):
    """Preview for write_file — diff on overwrite, compact line body for new files."""

    def compose(self) -> ComposeResult:
        """Compose file path header and content or unified diff."""
        file_path = self.data.get("file_path", "")
        content = self.data.get("content", "")
        is_new_file = bool(self.data.get("is_new_file"))
        diff_lines: list[str] = self.data.get("diff_lines", [])

        if not is_new_file and diff_lines:
            yield from self._compose_overwrite_diff(file_path, diff_lines)
            return

        lines = content.split("\n")
        total_lines = len(lines)

        if is_new_file:
            extra = "new file" if not self._finalized else ""
            yield from self._yield_compact_header(file_path, extra=extra)
        else:
            yield from self._yield_compact_header(
                file_path,
                additions=total_lines if content else 0,
            )

        if not content:
            yield Static("Empty file", classes="file-change-preview-body")
            return

        # Compact line-by-line rendering (matching DiffMessage style)
        yield from self._compose_content_lines(lines, total_lines)

    def _compose_content_lines(self, lines: list[str], total_lines: int) -> ComposeResult:
        """Render content as compact line-by-line widgets with gutter bars."""
        colors = theme.get_theme_colors()
        glyphs = get_glyphs()

        # Calculate line number width
        max_line = total_lines
        width = max(3, len(str(max_line)))

        shown_lines = lines[:TOOL_APPROVAL_BODY_MAX_LINES]
        remaining = total_lines - TOOL_APPROVAL_BODY_MAX_LINES

        for i, line in enumerate(shown_lines, start=1):
            yield Static(
                Content.assemble(
                    (f"{glyphs.gutter_bar}{i:>{width}}", f"{colors.success} bold"),
                    f"{DIFF_CODE_GAP}{line}",
                ),
                classes="diff-line-added",
            )

        if remaining > 0:
            yield Static(Content.styled(f"... ({remaining} more lines)", "dim"))

    def _compose_overwrite_diff(self, file_path: str, diff_lines: list[str]) -> ComposeResult:
        """Render unified diff when write_file replaces existing content."""
        old_string = self.data.get("old_string", "")
        new_string = self.data.get("new_string", "")
        additions, deletions = _count_diff_stats(diff_lines, old_string, new_string)
        yield from self._yield_compact_header(file_path, additions=additions, deletions=deletions)
        if not diff_lines:
            yield Static("No changes to display", classes="file-change-preview-body")
            return
        yield from self._render_diff_lines_only(diff_lines)


class DeleteFilePreviewWidget(FileChangePreviewWidget):
    """Preview for delete_file — path and sample of removed lines."""

    def compose(self) -> ComposeResult:
        """Compose deletion preview."""
        file_path = self.data.get("file_path", "")
        preview_lines: list[str] = self.data.get("preview_lines", [])
        total_lines = int(self.data.get("total_lines", 0))

        yield from self._yield_compact_header(file_path, deletions=total_lines)

        if not preview_lines:
            yield Static("No preview available", classes="file-change-preview-body")
            return

        colors = theme.get_theme_colors()
        glyphs = get_glyphs()
        width = max(3, len(str(total_lines)))

        for i, line in enumerate(preview_lines[:TOOL_APPROVAL_PREVIEW_LINES], start=1):
            yield Static(
                Content.assemble(
                    (f"{glyphs.gutter_bar}{i:>{width}}", f"{colors.error} bold"),
                    f"{DIFF_CODE_GAP}{line}",
                ),
                classes="diff-line-removed",
            )
        remaining = total_lines - len(preview_lines[:TOOL_APPROVAL_PREVIEW_LINES])
        if remaining > 0:
            yield Static(Content.styled(f"... ({remaining} more lines)", "dim"))


class EditFilePreviewWidget(FileChangePreviewWidget):
    """Preview for edit_file — unified diff style."""

    def compose(self) -> ComposeResult:
        """Compose diff preview."""
        yield from self._compose_edit_diff_body(show_line_range=False)

    def _compose_edit_diff_body(self, *, show_line_range: bool) -> ComposeResult:
        file_path = self.data.get("file_path", "")
        diff_lines = self.data.get("diff_lines", [])
        old_string = self.data.get("old_string", "")
        new_string = self.data.get("new_string", "")

        additions, deletions = _count_diff_stats(diff_lines, old_string, new_string)
        extra = ""
        if show_line_range:
            start_line = self.data.get("start_line")
            end_line = self.data.get("end_line")
            if isinstance(start_line, int) and isinstance(end_line, int):
                extra = f"lines {start_line}–{end_line}"
        yield from self._yield_compact_header(
            file_path,
            additions=additions,
            deletions=deletions,
            extra=extra,
        )

        if not diff_lines and not old_string and not new_string:
            yield Static("No changes to display", classes="file-change-preview-body")
        elif diff_lines:
            yield from self._render_diff_lines_only(diff_lines)
        else:
            yield from self._render_strings_only(old_string, new_string)

    def _render_strings_only(self, old_string: str, new_string: str) -> ComposeResult:
        colors = theme.get_theme_colors()
        if old_string:
            yield Static(
                Content.styled("Removing:", f"bold {colors.error}"),
                classes="file-change-preview-section-label",
            )
            yield from self._render_string_lines(old_string, is_addition=False)
        if new_string:
            yield Static(
                Content.styled("Adding:", f"bold {colors.success}"),
                classes="file-change-preview-section-label",
            )
            yield from self._render_string_lines(new_string, is_addition=True)


class EditFileLinesPreviewWidget(EditFilePreviewWidget):
    """Preview for edit_file_lines — line range + segment diff."""

    def compose(self) -> ComposeResult:
        """Compose line-range edit preview."""
        yield from self._compose_edit_diff_body(show_line_range=True)


class GenericFilePreviewWidget(FileChangePreviewWidget):
    """Fallback preview — key/value args."""

    def compose(self) -> ComposeResult:
        file_path = str(self.data.get("file_path") or self.data.get("path") or "").strip()
        if file_path:
            yield from self._yield_compact_header(file_path)
        elif self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-header",
            )
        for key, value in self.data.items():
            if value is None:
                continue
            value_str = str(value)
            if len(value_str) > TOOL_APPROVAL_VALUE_PREVIEW_CHARS:
                hidden = len(value_str) - TOOL_APPROVAL_VALUE_PREVIEW_CHARS
                value_str = (
                    value_str[:TOOL_APPROVAL_VALUE_PREVIEW_CHARS] + f"... ({hidden} more chars)"
                )
            yield Static(f"{key}: {value_str}", markup=False, classes="file-change-preview-body")


def unified_diff_body_lines(old_string: str, new_string: str) -> list[str]:
    """Return unified diff lines without ---/+++ headers (for edit_file previews)."""
    if not old_string and not new_string:
        return []
    old_lines = old_string.split("\n") if old_string else []
    new_lines = new_string.split("\n") if new_string else []
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="before",
        tofile="after",
        lineterm="",
        n=3,
    )
    diff_list = list(diff)
    return diff_list[2:] if len(diff_list) > 2 else diff_list  # noqa: PLR2004
