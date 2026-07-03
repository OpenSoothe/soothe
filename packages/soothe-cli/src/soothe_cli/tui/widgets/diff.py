"""Diff line composition helpers for unified diffs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import APPROVAL_DIFF_MAX_LINES

if TYPE_CHECKING:
    from textual.app import ComposeResult

_HUNK_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)")
# Two spaces after the line number so context/add/remove rows align.
DIFF_CODE_GAP = "  "


def split_unified_diff_body_line(line: str) -> tuple[str | None, str]:
    """Split a unified-diff body line into marker and payload.

    Args:
        line: One line from a unified diff body (excluding ``---``/``+++`` headers).

    Returns:
        ``(marker, content)`` where marker is ``+``, ``-``, `` `` for diff rows,
        or ``None`` for hunk headers, truncation markers, and other lines.
    """
    if not line:
        return None, ""
    marker = line[0]
    if marker in "+- ":
        return marker, line[1:]
    return None, line


def format_diff_row_plain(
    marker: str,
    content: str,
    *,
    line_num: int,
    width: int,
    gutter_bar: str = "▌",
    box_vertical: str = "│",
) -> str:
    """Format one diff row as plain text with aligned code columns.

    Args:
        marker: Unified diff marker (``+``, ``-``, or space for context).
        content: Line payload after the marker.
        line_num: Old/new line number to display.
        width: Width of the line-number column.
        gutter_bar: Gutter glyph for added/removed rows.
        box_vertical: Gutter glyph for context rows.

    Returns:
        Plain-text row used by tests to verify indentation alignment.
    """
    if marker == " ":
        gutter = box_vertical
    else:
        gutter = gutter_bar
    return f"{gutter}{line_num:>{width}}{DIFF_CODE_GAP}{content}"


def _max_diff_line_number(lines: list[str]) -> int:
    max_line = 0
    for line in lines:
        if m := _HUNK_RE.match(line):
            max_line = max(max_line, int(m.group(1)), int(m.group(2)))
    return max_line


def _render_diff_row(
    marker: str,
    content: str,
    *,
    line_num: int,
    width: int,
    glyphs: Any,
    colors: Any,
) -> Static:
    """Render one diff body row with aligned gutter, line number, and code."""
    if marker == " ":
        return Static(
            Content.assemble(
                (f"{glyphs.box_vertical}{line_num:>{width}}", "dim"),
                f"{DIFF_CODE_GAP}{content}",
            ),
            classes="diff-context",
        )
    if marker == "-":
        return Static(
            Content.assemble(
                (f"{glyphs.gutter_bar}{line_num:>{width}}", f"{colors.error} bold"),
                f"{DIFF_CODE_GAP}{content}",
            ),
            classes="diff-line-removed",
        )
    return Static(
        Content.assemble(
            (f"{glyphs.gutter_bar}{line_num:>{width}}", f"{colors.success} bold"),
            f"{DIFF_CODE_GAP}{content}",
        ),
        classes="diff-line-added",
    )


def compose_diff_line_list(
    diff_lines: list[str],
    max_lines: int | None = APPROVAL_DIFF_MAX_LINES,
) -> ComposeResult:
    """Yield per-line Static widgets for unified diff body lines.

    Args:
        diff_lines: Unified diff lines (may include ``---``/``+++`` headers).
        max_lines: Maximum number of rendered body lines (None for unlimited).

    Yields:
        Static widgets for each diff row.
    """
    if not diff_lines:
        yield Static(Content.styled("No changes detected", "dim"))
        return

    colors = theme.get_theme_colors()
    glyphs = get_glyphs()
    width = max(3, len(str(_max_diff_line_number(diff_lines) + len(diff_lines))))

    old_num = new_num = 0
    lines_shown = 0

    for line in diff_lines:
        if max_lines is not None and lines_shown >= max_lines:
            yield Static(Content.styled(f"... ({len(diff_lines) - lines_shown} more lines)", "dim"))
            break

        if line.startswith(("---", "+++")):
            continue

        if m := _HUNK_RE.match(line):
            old_num, new_num = int(m.group(1)), int(m.group(2))
            continue

        marker, content = split_unified_diff_body_line(line)
        if marker == "-":
            yield _render_diff_row(
                marker,
                content,
                line_num=old_num,
                width=width,
                glyphs=glyphs,
                colors=colors,
            )
            old_num += 1
            lines_shown += 1
        elif marker == "+":
            yield _render_diff_row(
                marker,
                content,
                line_num=new_num,
                width=width,
                glyphs=glyphs,
                colors=colors,
            )
            new_num += 1
            lines_shown += 1
        elif marker == " ":
            yield _render_diff_row(
                marker,
                content,
                line_num=old_num,
                width=width,
                glyphs=glyphs,
                colors=colors,
            )
            old_num += 1
            new_num += 1
            lines_shown += 1
        elif line.strip() == "...":
            yield Static(Content.styled("...", "dim"))
            lines_shown += 1
        elif line.strip():
            yield Static(Content.styled(line, "dim"))
            lines_shown += 1


def compose_diff_lines(
    diff: str,
    max_lines: int | None = APPROVAL_DIFF_MAX_LINES,
) -> ComposeResult:
    """Yield per-line Static widgets for a unified diff.

    Each added/removed line gets a CSS class (``.diff-line-added``,
    ``.diff-line-removed``) so background colors are driven by CSS variables
    and update automatically on theme change.

    Args:
        diff: Unified diff string.
        max_lines: Maximum number of diff lines to show (None for unlimited).

    Yields:
        Static widgets — stats header plus one widget per diff line.
    """
    if not diff:
        yield Static(Content.styled("No changes detected", "dim"))
        return

    lines = diff.splitlines()
    additions = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    deletions = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))

    stats_parts: list[str | tuple[str, str] | Content] = []
    colors = theme.get_theme_colors()
    if additions:
        stats_parts.append((f"+{additions}", colors.success))
    if deletions:
        if stats_parts:
            stats_parts.append(" ")
        stats_parts.append((f"-{deletions}", colors.error))
    if stats_parts:
        yield Static(Content.assemble(*stats_parts))

    yield from compose_diff_line_list(lines, max_lines)
