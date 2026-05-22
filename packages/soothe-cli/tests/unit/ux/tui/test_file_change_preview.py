"""Tests for non-blocking filesystem change preview widgets."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.runtime.state.file_tracker import (
    apply_edit_file_lines_to_content,
    extract_line_range_text,
)
from soothe_cli.tui.file_change_notify import mount_file_change_preview, textual_widget_id
from soothe_cli.tui.file_change_renderers import build_file_change_preview
from soothe_cli.tui.widgets.file_change_preview import (
    DeleteFilePreviewWidget,
    EditFileLinesPreviewWidget,
    EditFilePreviewWidget,
    WriteFilePreviewWidget,
)


def test_textual_widget_id_sanitizes_unified_tool_call_id() -> None:
    """Unified tool call ids with colons become Textual-safe widget ids."""
    assert textual_widget_id("file-preview", "JWZ_01:s:write_file:23") == (
        "file-preview-JWZ_01_s_write_file_23"
    )


def test_build_write_file_preview_marks_new_file(tmp_path: Path) -> None:
    """write_file preview flags new files when the path does not exist yet."""
    target = tmp_path / "new.txt"
    built = build_file_change_preview(
        "write_file",
        {"file_path": str(target), "content": "hello"},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is WriteFilePreviewWidget
    assert data["is_new_file"] is True
    assert data["content"] == "hello"


def test_build_write_file_preview_shows_diff_on_overwrite(tmp_path: Path) -> None:
    """write_file on an existing path includes unified diff lines."""
    target = tmp_path / "existing.txt"
    target.write_text("old line\n", encoding="utf-8")
    built = build_file_change_preview(
        "write_file",
        {"file_path": str(target), "content": "new line\n"},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is WriteFilePreviewWidget
    assert data["is_new_file"] is False
    assert any(line.startswith("-") or line.startswith("+") for line in data["diff_lines"])


def test_build_edit_file_preview_has_diff_lines() -> None:
    """edit_file preview includes unified diff body lines."""
    built = build_file_change_preview(
        "edit_file",
        {"file_path": "a.py", "old_string": "foo", "new_string": "bar"},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is EditFilePreviewWidget
    assert any(line.startswith("-") or line.startswith("+") for line in data["diff_lines"])


def test_build_edit_file_lines_preview_uses_line_range(tmp_path: Path) -> None:
    """edit_file_lines preview diffs the replaced segment against new_content."""
    target = tmp_path / "lines.py"
    target.write_text("keep\nold_a\nold_b\ntail\n", encoding="utf-8")
    built = build_file_change_preview(
        "edit_file_lines",
        {
            "file_path": str(target),
            "start_line": 2,
            "end_line": 3,
            "new_content": "new_a\nnew_b",
        },
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is EditFileLinesPreviewWidget
    assert data["start_line"] == 2
    assert data["end_line"] == 3
    assert "-old_a" in "".join(data["diff_lines"]) or "-old_b" in "".join(data["diff_lines"])
    assert "+new_a" in "".join(data["diff_lines"])

    segment = extract_line_range_text(target.read_text(encoding="utf-8"), 2, 3)
    assert "old_a" in segment
    after = apply_edit_file_lines_to_content(
        target.read_text(encoding="utf-8"), 2, 3, "new_a\nnew_b"
    )
    assert after is not None
    assert "new_a" in after
    assert "old_a" not in after


def test_build_delete_file_preview_reads_disk(tmp_path: Path) -> None:
    """delete_file preview samples existing file content."""
    target = tmp_path / "gone.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")
    built = build_file_change_preview(
        "delete_file",
        {"file_path": str(target)},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is DeleteFilePreviewWidget
    assert data["total_lines"] == 2
    assert "line1" in data["preview_lines"][0]


@pytest.mark.asyncio
async def test_mount_file_change_preview_accepts_unified_tool_call_id() -> None:
    """Mount succeeds when tool_call_id contains colons (unified id format)."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._mount_message = AsyncMock()

    args = {"file_path": "/tmp/x.txt", "content": "body"}
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="JWZ_01:s:write_file:23",
        assistant_id=None,
    )

    assert adapter._mount_message.await_count == 1
    mounted = adapter._mount_message.await_args_list[0].args[0]
    assert mounted.id == "file-preview-JWZ_01_s_write_file_23"
    assert "JWZ_01:s:write_file:23" in adapter._file_change_previews_shown


@pytest.mark.asyncio
async def test_mount_file_change_preview_dedupes_by_tool_call_id() -> None:
    """Only one preview card is mounted per tool_call_id per turn."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._mount_message = AsyncMock()

    args = {"file_path": "/tmp/x.txt", "content": "body"}
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="tc-1",
        assistant_id=None,
    )
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="tc-1",
        assistant_id=None,
    )

    assert adapter._mount_message.await_count == 1
    assert "tc-1" in adapter._file_change_previews_shown


@pytest.mark.asyncio
async def test_mount_file_change_preview_marks_shown_after_mount_failure() -> None:
    """A failed mount is not retried on subsequent streaming updates for the same id."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._mount_message = AsyncMock(side_effect=RuntimeError("mount failed"))

    args = {"file_path": "/tmp/x.txt", "content": "body"}
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="tc-fail",
        assistant_id=None,
    )
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="tc-fail",
        assistant_id=None,
    )

    assert adapter._mount_message.await_count == 1
    assert "tc-fail" in adapter._file_change_previews_shown


@pytest.mark.asyncio
async def test_mount_file_change_preview_propagates_cancelled_error() -> None:
    """User interrupt during mount must propagate CancelledError."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._mount_message = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await mount_file_change_preview(
            adapter,
            tool_name="write_file",
            args={"file_path": "/tmp/x.txt", "content": "body"},
            tool_call_id="tc-cancel",
            assistant_id=None,
        )

    assert "tc-cancel" not in adapter._file_change_previews_shown
