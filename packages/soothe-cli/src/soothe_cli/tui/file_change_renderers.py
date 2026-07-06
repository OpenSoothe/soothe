"""Build preview widget data for filesystem tool calls."""

from __future__ import annotations

from typing import Any

from soothe_cli.runtime.state.file_tracker import (
    FILE_CHANGE_TOOLS,
    FileOperationRecord,
    apply_edit_file_lines_to_content,
    apply_insert_lines_to_content,
    extract_line_range_text,
    parse_insert_line_arg,
    parse_line_range_args,
    read_physical_file_text,
    resolve_physical_path,
)
from soothe_cli.tui.preview_limits import TOOL_APPROVAL_PREVIEW_LINES
from soothe_cli.tui.widgets.file_change_preview import (
    DeleteFilePreviewWidget,
    EditFileLinesPreviewWidget,
    EditFilePreviewWidget,
    FileChangePreviewWidget,
    GenericFilePreviewWidget,
    InsertLinesPreviewWidget,
    WriteFilePreviewWidget,
    unified_diff_body_lines,
)


def build_file_change_preview(
    tool_name: str,
    args: dict[str, Any],
    *,
    assistant_id: str | None,
) -> tuple[type[FileChangePreviewWidget], dict[str, Any]] | None:
    """Return widget class and data for a filesystem tool preview, or None.

    Args:
        tool_name: Tool name (must be in ``FILE_CHANGE_TOOLS``).
        args: Parsed tool arguments.
        assistant_id: Agent id for ``/memories/`` path resolution.

    Returns:
        ``(widget_class, data)`` or None when the tool is not a file-change tool.
    """
    if tool_name not in FILE_CHANGE_TOOLS:
        return None

    path_str = str(args.get("file_path") or args.get("path") or "")

    if tool_name == "write_file":
        content = str(args.get("content") or "")
        file_extension = "text"
        if "." in path_str:
            file_extension = path_str.rsplit(".", 1)[-1]
        physical = resolve_physical_path(path_str, assistant_id)
        before = ""
        if physical and physical.is_file():
            before = read_physical_file_text(physical) or ""
        is_new_file = not before
        data: dict[str, Any] = {
            "file_path": path_str,
            "content": content,
            "file_extension": file_extension,
            "is_new_file": is_new_file,
        }
        if not is_new_file and before != content:
            data["diff_lines"] = unified_diff_body_lines(before, content)
            data["old_string"] = before
            data["new_string"] = content
        return WriteFilePreviewWidget, data

    if tool_name == "edit_file":
        old_string = str(args.get("old_string") or "")
        new_string = str(args.get("new_string") or "")
        return EditFilePreviewWidget, {
            "file_path": path_str,
            "diff_lines": unified_diff_body_lines(old_string, new_string),
            "old_string": old_string,
            "new_string": new_string,
        }

    if tool_name == "edit_file_lines":
        line_range = parse_line_range_args(args)
        if line_range is None:
            return GenericFilePreviewWidget, dict(args)
        start_line, end_line = line_range
        new_string = str(args.get("new_content") or "")
        before = ""
        physical = resolve_physical_path(path_str, assistant_id)
        if physical and physical.is_file():
            before = read_physical_file_text(physical) or ""
        old_segment = extract_line_range_text(before, start_line, end_line) if before else ""
        return EditFileLinesPreviewWidget, {
            "file_path": path_str,
            "start_line": start_line,
            "end_line": end_line,
            "diff_lines": unified_diff_body_lines(old_segment, new_string),
            "old_string": old_segment,
            "new_string": new_string,
        }

    if tool_name == "insert_lines":
        line = parse_insert_line_arg(args)
        if line is None:
            return GenericFilePreviewWidget, dict(args)
        insert_content = str(args.get("content") or "")
        before = ""
        physical = resolve_physical_path(path_str, assistant_id)
        if physical and physical.is_file():
            before = read_physical_file_text(physical) or ""
        after_text = apply_insert_lines_to_content(before, line, insert_content) or before
        return InsertLinesPreviewWidget, {
            "file_path": path_str,
            "insert_line": line,
            "diff_lines": unified_diff_body_lines(before, after_text),
            "old_string": before,
            "new_string": after_text,
        }

    if tool_name == "delete_lines":
        line_range = parse_line_range_args(args)
        if line_range is None:
            return GenericFilePreviewWidget, dict(args)
        start_line, end_line = line_range
        before = ""
        physical = resolve_physical_path(path_str, assistant_id)
        if physical and physical.is_file():
            before = read_physical_file_text(physical) or ""
        old_segment = extract_line_range_text(before, start_line, end_line) if before else ""
        after_text = (
            apply_edit_file_lines_to_content(before, start_line, end_line, "") if before else ""
        )
        if after_text is None:
            after_text = before
        return EditFileLinesPreviewWidget, {
            "file_path": path_str,
            "start_line": start_line,
            "end_line": end_line,
            "diff_lines": unified_diff_body_lines(before, after_text),
            "old_string": old_segment,
            "new_string": "",
        }

    if tool_name == "apply_diff":
        diff_text = str(args.get("diff") or "")
        before = ""
        physical = resolve_physical_path(path_str, assistant_id)
        if physical and physical.is_file():
            before = read_physical_file_text(physical) or ""
        diff_lines = [ln for ln in diff_text.splitlines() if ln.strip()]
        return EditFilePreviewWidget, {
            "file_path": path_str,
            "diff_lines": diff_lines,
            "old_string": before,
            "new_string": "",
        }

    if tool_name == "delete_file":
        content = ""
        physical = resolve_physical_path(path_str, assistant_id)
        if physical and physical.is_file():
            try:
                content = physical.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                content = ""
        lines = content.splitlines() if content else []
        return DeleteFilePreviewWidget, {
            "file_path": path_str,
            "preview_lines": lines[:TOOL_APPROVAL_PREVIEW_LINES],
            "total_lines": len(lines),
        }

    return GenericFilePreviewWidget, dict(args)


def update_preview_data_from_record(data: dict[str, Any], record: FileOperationRecord) -> None:
    """Refresh an in-flight preview widget's data from a completed tracker record."""
    data["file_path"] = record.display_path

    if record.tool_name == "write_file":
        before = record.before_content or ""
        after = record.after_content or ""
        if not before:
            data["is_new_file"] = True
            data["content"] = after
            data.pop("diff_lines", None)
            data.pop("old_string", None)
            data.pop("new_string", None)
        else:
            data["is_new_file"] = False
            data["content"] = after
            if record.diff:
                data["diff_lines"] = record.diff.splitlines()
                data["old_string"] = before
                data["new_string"] = after
        return

    if record.tool_name == "delete_file":
        before = record.before_content or ""
        lines = before.splitlines()
        data["preview_lines"] = lines[:TOOL_APPROVAL_PREVIEW_LINES]
        data["total_lines"] = len(lines)
        return

    if record.tool_name == "edit_file_lines":
        line_range = parse_line_range_args(record.args)
        if line_range is not None:
            data["start_line"], data["end_line"] = line_range

    if record.tool_name == "insert_lines":
        line = parse_insert_line_arg(record.args)
        if line is not None:
            data["insert_line"] = line

    if record.tool_name == "delete_lines":
        line_range = parse_line_range_args(record.args)
        if line_range is not None:
            data["start_line"], data["end_line"] = line_range

    if record.diff:
        data["diff_lines"] = record.diff.splitlines()
        data["old_string"] = record.before_content or ""
        data["new_string"] = record.after_content or ""
