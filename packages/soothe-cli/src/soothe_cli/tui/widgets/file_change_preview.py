"""Non-blocking file change preview widgets (write / edit / delete).

Shown when a filesystem tool call is recognized so the user can see what will
change. Unlike the removed HITL approval flow, these widgets do not block execution.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Markdown, Static

from soothe_cli.tui import theme
from soothe_cli.tui.preview_limits import (
    TOOL_APPROVAL_BODY_MAX_LINES,
    TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES,
    TOOL_APPROVAL_PREVIEW_LINES,
    TOOL_APPROVAL_VALUE_PREVIEW_CHARS,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult


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


def _file_header(file_path: str, additions: int = 0, deletions: int = 0) -> ComposeResult:
    """Yield the file path header with optional +N -M stats."""
    stats = _format_stats(additions, deletions)
    yield Static(
        Content.assemble(
            Content.from_markup("[bold cyan]File:[/bold cyan] $path  ", path=file_path),
            stats,
        )
    )
    yield Static("")


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
    """Base class for filesystem change preview cards."""

    def __init__(self, data: dict[str, Any], *, action_label: str = "") -> None:
        """Initialize with renderer-built data dict."""
        super().__init__(classes="file-change-preview")
        self.data = data
        self._action_label = action_label.strip()

    def compose(self) -> ComposeResult:  # noqa: PLR6301
        """Default compose — subclasses override."""
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
            )
        yield Static("Change details not available", classes="file-change-preview-body")

    def _render_diff_lines_only(self, diff_lines: list[str]) -> ComposeResult:
        lines_shown = 0
        for line in diff_lines:
            if lines_shown >= TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES:
                yield Static(
                    Content.styled(f"... ({len(diff_lines) - lines_shown} more lines)", "dim")
                )
                break
            if line.startswith(("@@", "---", "+++")):
                continue
            widget = self._render_diff_line(line)
            if widget:
                yield widget
                lines_shown += 1

    @staticmethod
    def _render_diff_line(line: str) -> Static | None:
        raw = line[1:] if len(line) > 1 else ""
        if line.startswith("-"):
            return Static(Content.from_markup("- $text", text=raw), classes="diff-removed")
        if line.startswith("+"):
            return Static(Content.from_markup("+ $text", text=raw), classes="diff-added")
        if line.startswith(" "):
            return Static(Content.from_markup("  $text", text=raw), classes="diff-context")
        if line.strip():
            return Static(line, markup=False)
        return None

    @staticmethod
    def _render_string_lines(text: str, *, is_addition: bool) -> ComposeResult:
        lines = text.split("\n")
        sign = "+" if is_addition else "-"
        cls = "diff-added" if is_addition else "diff-removed"
        for line in lines[:TOOL_APPROVAL_PREVIEW_LINES]:
            yield Static(Content.from_markup(f"{sign} $text", text=line), classes=cls)
        if len(lines) > TOOL_APPROVAL_PREVIEW_LINES:
            remaining = len(lines) - TOOL_APPROVAL_PREVIEW_LINES
            yield Static(Content.styled(f"... ({remaining} more lines)", "dim"))


class WriteFilePreviewWidget(FileChangePreviewWidget):
    """Preview for write_file — diff on overwrite, syntax body for new files."""

    def compose(self) -> ComposeResult:
        """Compose file path header and content or unified diff."""
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
            )

        file_path = self.data.get("file_path", "")
        content = self.data.get("content", "")
        file_extension = self.data.get("file_extension", "text")
        is_new_file = bool(self.data.get("is_new_file"))
        diff_lines: list[str] = self.data.get("diff_lines", [])

        if not is_new_file and diff_lines:
            yield from self._compose_overwrite_diff(file_path, diff_lines)
            return

        lines = content.split("\n")
        total_lines = len(lines)

        if is_new_file:
            yield Static(
                Content.from_markup(
                    "[bold cyan]File:[/bold cyan] $path  [dim](new file)[/dim]",
                    path=file_path,
                )
            )
            yield Static("")
        else:
            yield from _file_header(file_path, additions=total_lines if content else 0)

        if not content:
            yield Static("Empty file", classes="file-change-preview-body")
            return

        if total_lines > TOOL_APPROVAL_BODY_MAX_LINES:
            shown_lines = lines[:TOOL_APPROVAL_BODY_MAX_LINES]
            remaining = total_lines - TOOL_APPROVAL_BODY_MAX_LINES
            truncated_content = "\n".join(shown_lines) + f"\n... ({remaining} more lines)"
            yield Markdown(f"```{file_extension}\n{truncated_content}\n```")
        else:
            yield Markdown(f"```{file_extension}\n{content}\n```")

    def _compose_overwrite_diff(self, file_path: str, diff_lines: list[str]) -> ComposeResult:
        """Render unified diff when write_file replaces existing content."""
        old_string = self.data.get("old_string", "")
        new_string = self.data.get("new_string", "")
        additions, deletions = _count_diff_stats(diff_lines, old_string, new_string)
        yield from _file_header(file_path, additions, deletions)
        if not diff_lines:
            yield Static("No changes to display", classes="file-change-preview-body")
            return
        yield from self._render_diff_lines_only(diff_lines)


class DeleteFilePreviewWidget(FileChangePreviewWidget):
    """Preview for delete_file — path and sample of removed lines."""

    def compose(self) -> ComposeResult:
        """Compose deletion preview."""
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
            )

        file_path = self.data.get("file_path", "")
        preview_lines: list[str] = self.data.get("preview_lines", [])
        total_lines = int(self.data.get("total_lines", 0))

        yield from _file_header(file_path, deletions=total_lines)
        yield Static(Content.styled("Deleting file", "bold"))

        if not preview_lines:
            yield Static("No preview available", classes="file-change-preview-body")
            return

        yield Static("")
        for line in preview_lines[:TOOL_APPROVAL_PREVIEW_LINES]:
            yield Static(
                Content.from_markup("- $text", text=line),
                classes="diff-removed",
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
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
            )

        file_path = self.data.get("file_path", "")
        if show_line_range:
            start_line = self.data.get("start_line")
            end_line = self.data.get("end_line")
            if isinstance(start_line, int) and isinstance(end_line, int):
                yield Static(
                    Content.from_markup(
                        "[bold cyan]File:[/bold cyan] $path  [dim]lines $start–$end[/dim]",
                        path=file_path,
                        start=start_line,
                        end=end_line,
                    )
                )
                yield Static("")

        diff_lines = self.data.get("diff_lines", [])
        old_string = self.data.get("old_string", "")
        new_string = self.data.get("new_string", "")

        additions, deletions = _count_diff_stats(diff_lines, old_string, new_string)
        if not show_line_range:
            yield from _file_header(file_path, additions, deletions)
        elif additions or deletions:
            yield Static(_format_stats(additions, deletions))

        if not diff_lines and not old_string and not new_string:
            yield Static("No changes to display", classes="file-change-preview-body")
        elif diff_lines:
            yield from self._render_diff_lines_only(diff_lines)
        else:
            yield from self._render_strings_only(old_string, new_string)

    def _render_strings_only(self, old_string: str, new_string: str) -> ComposeResult:
        colors = theme.get_theme_colors()
        if old_string:
            yield Static(Content.styled("Removing:", f"bold {colors.error}"))
            yield from self._render_string_lines(old_string, is_addition=False)
            yield Static("")
        if new_string:
            yield Static(Content.styled("Adding:", f"bold {colors.success}"))
            yield from self._render_string_lines(new_string, is_addition=True)


class EditFileLinesPreviewWidget(EditFilePreviewWidget):
    """Preview for edit_file_lines — line range + segment diff."""

    def compose(self) -> ComposeResult:
        """Compose line-range edit preview."""
        yield from self._compose_edit_diff_body(show_line_range=True)


class GenericFilePreviewWidget(FileChangePreviewWidget):
    """Fallback preview — key/value args."""

    def compose(self) -> ComposeResult:
        if self._action_label:
            yield Static(
                Content.from_markup("[bold]$label[/bold]", label=self._action_label),
                classes="file-change-preview-label",
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
