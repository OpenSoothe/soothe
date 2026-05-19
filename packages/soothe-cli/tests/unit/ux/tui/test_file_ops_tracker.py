"""Tests for TUI file operation tracking and diff generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from soothe_cli.tui.file_ops import (
    FileOpTracker,
    file_change_action_label,
    track_file_operation,
)


def test_write_file_produces_diff_after_completion(tmp_path: Path) -> None:
    """Tracked write_file shows a unified diff after the tool result."""
    target = tmp_path / "hello.txt"
    tracker = FileOpTracker(assistant_id=None)
    args = {"file_path": str(target), "content": "line one\nline two\n"}
    track_file_operation(tracker, "write_file", args, "tc-1")

    target.write_text("line one\nline two\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(
            tool_call_id="tc-1",
            content="ok",
            status="success",
        )
    )

    assert record is not None
    assert record.diff is not None
    assert "+line one" in record.diff
    assert file_change_action_label(record) == "New file"


def test_edit_file_produces_diff(tmp_path: Path) -> None:
    """Tracked edit_file diff reflects on-disk before/after content."""
    target = tmp_path / "edit.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "edit_file",
        {"file_path": str(target), "old_string": "beta", "new_string": "gamma"},
        "tc-edit",
    )

    target.write_text("alpha\ngamma\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-edit", content="ok", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "-beta" in record.diff
    assert "+gamma" in record.diff
    assert file_change_action_label(record) == "Updated"


def test_delete_file_produces_deletion_diff(tmp_path: Path) -> None:
    """Tracked delete_file diff shows removed lines."""
    target = tmp_path / "remove.txt"
    target.write_text("gone\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(tracker, "delete_file", {"file_path": str(target)}, "tc-del")

    target.unlink()
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-del", content="Deleted", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "-gone" in record.diff
    assert file_change_action_label(record) == "Deleted"
