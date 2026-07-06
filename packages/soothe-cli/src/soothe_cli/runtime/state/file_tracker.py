"""Helpers for tracking file operations and computing diffs for CLI display."""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from soothe_sdk.tools.metadata import get_file_write_tool_names

from soothe_cli.tui.preview_limits import APPROVAL_DIFF_MAX_LINES

logger = logging.getLogger(__name__)

FileOpStatus = Literal["pending", "success", "error"]

FILE_CHANGE_TOOLS: frozenset[str] = get_file_write_tool_names()
"""Filesystem tools that produce before/after diffs in the TUI chat."""


def _safe_read(path: Path) -> str | None:
    """Read file content, returning None on failure.

    Returns:
        File content as string, or None if reading fails.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.debug("Failed to read file %s: %s", path, e)
        return None


def read_physical_file_text(path: Path | None) -> str | None:
    """Read UTF-8 text from a resolved physical path.

    Returns:
        File content, or None when ``path`` is missing or unreadable.
    """
    if path is None:
        return None
    return _safe_read(path)


def _count_lines(text: str) -> int:
    """Count lines in text, treating empty strings as zero lines.

    Returns:
        Number of lines in the text.
    """
    if not text:
        return 0
    return len(text.splitlines())


def compute_unified_diff(
    before: str,
    after: str,
    display_path: str,
    *,
    max_lines: int | None = 800,
    context_lines: int = 3,
) -> str | None:
    """Compute a unified diff between before and after content.

    Args:
        before: Original content
        after: New content
        display_path: Path for display in diff headers
        max_lines: Maximum number of diff lines (None for unlimited)
        context_lines: Number of context lines around changes (default 3)

    Returns:
        Unified diff string or None if no changes
    """
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{display_path} (before)",
            tofile=f"{display_path} (after)",
            lineterm="",
            n=context_lines,
        )
    )
    if not diff_lines:
        return None
    if max_lines is not None and len(diff_lines) > max_lines:
        truncated = diff_lines[: max_lines - 1]
        truncated.append("...")
        return "\n".join(truncated)
    return "\n".join(diff_lines)


@dataclass
class FileOpMetrics:
    """Line and byte level metrics for a file operation."""

    lines_read: int = 0
    start_line: int | None = None
    end_line: int | None = None
    lines_written: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    bytes_written: int = 0


@dataclass
class FileOperationRecord:
    """Track a single filesystem tool call."""

    tool_name: str
    display_path: str
    physical_path: Path | None
    tool_call_id: str | None
    args: dict[str, Any] = field(default_factory=dict)
    status: FileOpStatus = "pending"
    error: str | None = None
    metrics: FileOpMetrics = field(default_factory=FileOpMetrics)
    diff: str | None = None
    before_content: str | None = None
    after_content: str | None = None
    read_output: str | None = None


def resolve_physical_path(path_str: str | None, assistant_id: str | None) -> Path | None:
    """Convert a virtual/relative path to a physical filesystem path.

    Returns:
        Resolved physical Path, or None if path is empty or resolution fails.
    """
    if not path_str:
        return None
    try:
        if assistant_id and path_str.startswith("/memories/"):
            from soothe_cli.tui.config import settings

            agent_dir = settings.get_agent_dir(assistant_id)
            suffix = path_str.removeprefix("/memories/").lstrip("/")
            return (agent_dir / suffix).resolve()
        path = Path(path_str)
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()
    except (OSError, ValueError):
        return None


def parse_insert_line_arg(args: dict[str, Any]) -> int | None:
    """Parse ``line`` from insert_lines tool args (1-indexed).

    Returns:
        Line number or None when missing or not an integer.
    """
    line = args.get("line")
    if isinstance(line, bool):
        return None
    if isinstance(line, int):
        return line
    if isinstance(line, float) and line.is_integer():
        return int(line)
    return None


def parse_line_range_args(args: dict[str, Any]) -> tuple[int, int] | None:
    """Parse ``start_line`` and ``end_line`` from tool args (1-indexed inclusive).

    Returns:
        ``(start_line, end_line)`` or None when missing or not integers.
    """
    start = args.get("start_line")
    end = args.get("end_line")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if isinstance(start, int) and isinstance(end, int):
        return start, end
    if (
        isinstance(start, float)
        and isinstance(end, float)
        and start.is_integer()
        and end.is_integer()
    ):
        return int(start), int(end)
    return None


def extract_line_range_text(content: str, start_line: int, end_line: int) -> str:
    """Return the text of lines ``start_line``..``end_line`` (1-indexed inclusive).

    Returns:
        Joined line text including original line endings, or empty when out of range.
    """
    lines = content.splitlines(keepends=True)
    total = len(lines)
    if total == 0:
        return ""
    if start_line < 1 or start_line > total or end_line < start_line:
        return ""
    end_line = min(end_line, total)
    return "".join(lines[start_line - 1 : end_line])


def apply_insert_lines_to_content(content: str, line: int, insert_content: str) -> str | None:
    """Insert ``insert_content`` before line ``line`` (matches middleware semantics).

    Returns:
        Modified file text, or None when ``line`` is out of range for ``content``.
    """
    lines = content.splitlines(keepends=True)
    total = len(lines)
    if total == 0 and content:
        lines = [content]
        total = 1
    if line < 1 or line > total + 1:
        return None
    new_lines = insert_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    lines[line - 1 : line - 1] = new_lines
    return "".join(lines)


def apply_edit_file_lines_to_content(
    content: str,
    start_line: int,
    end_line: int,
    new_content: str,
) -> str | None:
    """Apply a line-range replacement to file content (matches middleware semantics).

    Returns:
        Modified file text, or None when the line range is invalid for ``content``.
    """
    lines = content.splitlines(keepends=True)
    total = len(lines)
    if total == 0 and content:
        lines = [content]
        total = 1
    if start_line < 1 or start_line > total or end_line < start_line or end_line > total:
        return None
    new_lines = new_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    lines[start_line - 1 : end_line] = new_lines
    return "".join(lines)


def format_display_path(path_str: str | None) -> str:
    """Format a path for display.

    Returns:
        Formatted path string suitable for display.
    """
    if not path_str:
        return "(unknown)"
    try:
        path = Path(path_str)
        if path.is_absolute():
            return path.name or str(path)
        return str(path)
    except (OSError, ValueError):
        return str(path_str)


class FileOpTracker:
    """Collect file operation metrics during a CLI interaction."""

    def __init__(self, *, assistant_id: str | None) -> None:
        """Initialize the tracker."""
        self.assistant_id = assistant_id
        self.active: dict[str | None, FileOperationRecord] = {}
        self.completed: list[FileOperationRecord] = []

    def start_operation(
        self, tool_name: str, args: dict[str, Any], tool_call_id: str | None
    ) -> None:
        """Begin tracking a file operation.

        Creates a record for the operation and captures on-disk content before
        write, edit, or delete.
        """
        if tool_name not in {"read_file", *FILE_CHANGE_TOOLS}:
            return
        path_str = str(args.get("file_path") or args.get("path") or "")
        display_path = format_display_path(path_str)
        record = FileOperationRecord(
            tool_name=tool_name,
            display_path=display_path,
            physical_path=resolve_physical_path(path_str, self.assistant_id),
            tool_call_id=tool_call_id,
            args=args,
        )
        if tool_name in FILE_CHANGE_TOOLS and record.physical_path:
            record.before_content = _safe_read(record.physical_path) or ""
        self.active[tool_call_id] = record

    def complete_with_message(self, tool_message: Any) -> FileOperationRecord | None:  # noqa: ANN401  # Tool message type is dynamic
        """Complete a file operation with the tool message result.

        Returns:
            The completed FileOperationRecord, or None if no matching operation.
        """
        tool_call_id = getattr(tool_message, "tool_call_id", None)
        record = self.active.get(tool_call_id)
        if record is None:
            return None

        content = tool_message.content
        if isinstance(content, list):
            # Some tool messages may return list segments; join them for analysis.
            joined = []
            for item in content:
                if isinstance(item, str):
                    joined.append(item)
                else:
                    joined.append(str(item))
            content_text = "\n".join(joined)
        else:
            content_text = str(content) if content is not None else ""

        if getattr(
            tool_message, "status", "success"
        ) != "success" or content_text.lower().startswith("error"):
            record.status = "error"
            record.error = content_text
            self._finalize(record)
            return record

        record.status = "success"

        if record.tool_name == "read_file":
            record.read_output = content_text
            lines = _count_lines(content_text)
            record.metrics.lines_read = lines
            offset = record.args.get("offset")
            limit = record.args.get("limit")
            if isinstance(offset, int):
                if offset > lines:
                    offset = 0
                record.metrics.start_line = offset + 1
                if lines:
                    record.metrics.end_line = offset + lines
            elif lines:
                record.metrics.start_line = 1
                record.metrics.end_line = lines
            if isinstance(limit, int) and lines > limit:
                record.metrics.end_line = (record.metrics.start_line or 1) + limit - 1
        elif record.tool_name == "delete_file":
            record.after_content = ""
            record.metrics.lines_removed = _count_lines(record.before_content or "")
        else:
            self._populate_after_content(record)
            if record.after_content is None:
                record.status = "error"
                record.error = "Could not read updated file content."
                self._finalize(record)
                return record
            record.metrics.lines_written = _count_lines(record.after_content)

        if record.tool_name in FILE_CHANGE_TOOLS:
            before_lines = _count_lines(record.before_content or "")
            after_text = record.after_content or ""
            record.diff = compute_unified_diff(
                record.before_content or "",
                after_text,
                record.display_path,
                max_lines=APPROVAL_DIFF_MAX_LINES,
            )
            if record.diff:
                record.metrics.lines_added = sum(
                    1
                    for line in record.diff.splitlines()
                    if line.startswith("+") and not line.startswith("+++")
                )
                record.metrics.lines_removed = sum(
                    1
                    for line in record.diff.splitlines()
                    if line.startswith("-") and not line.startswith("---")
                )
            elif record.tool_name == "write_file" and not (record.before_content or ""):
                record.metrics.lines_added = record.metrics.lines_written
            if record.tool_name != "delete_file":
                record.metrics.bytes_written = len(after_text.encode("utf-8"))
            if record.diff is None and (record.before_content or "") != after_text:
                record.diff = compute_unified_diff(
                    record.before_content or "",
                    after_text,
                    record.display_path,
                    max_lines=APPROVAL_DIFF_MAX_LINES,
                )
            if (
                record.diff is None
                and record.tool_name == "write_file"
                and before_lines != record.metrics.lines_written
            ):
                record.metrics.lines_added = max(record.metrics.lines_written - before_lines, 0)

        self._finalize(record)
        return record

    def _populate_after_content(self, record: FileOperationRecord) -> None:
        """Read the file content after the operation for diff computation."""
        if record.physical_path is None:
            record.after_content = None
            return
        record.after_content = _safe_read(record.physical_path)

    def _finalize(self, record: FileOperationRecord) -> None:
        self.completed.append(record)
        self.active.pop(record.tool_call_id, None)


def track_file_operation(
    tracker: FileOpTracker,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str | None,
) -> None:
    """Start tracking a file change tool if not already tracked for this call id."""
    if tool_name not in FILE_CHANGE_TOOLS:
        return
    tcid = str(tool_call_id).strip() if tool_call_id else ""
    if not tcid or tcid in tracker.active:
        return
    tracker.start_operation(tool_name, args, tcid)


def file_change_action_label(record: FileOperationRecord) -> str:
    """Human-readable label for a completed file operation (chat diff header)."""
    if record.tool_name == "delete_file":
        return "Deleted"
    if record.tool_name == "write_file" and not (record.before_content or ""):
        return "New file"
    if record.tool_name == "write_file":
        return "Written"
    if record.tool_name in ("edit_file", "edit_file_lines", "delete_lines", "apply_diff"):
        return "Updated"
    if record.tool_name == "insert_lines":
        return "Inserted"
    return "Changed"
