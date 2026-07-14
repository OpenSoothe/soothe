"""Tests for TUI file operation tracking and diff generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from soothe_cli.runtime.state.file_tracker import (
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
    assert file_change_action_label(record) == "Created"


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
    assert file_change_action_label(record) == "Edited"


def test_edit_file_lines_produces_diff(tmp_path: Path) -> None:
    """Tracked edit_file_lines shows a unified diff after the tool result."""
    target = tmp_path / "surgical.txt"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "edit_file_lines",
        {
            "file_path": str(target),
            "start_line": 2,
            "end_line": 2,
            "new_content": "LINE2\n",
        },
        "tc-lines",
    )

    target.write_text("line1\nLINE2\nline3\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-lines", content="ok", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "-line2" in record.diff
    assert "+LINE2" in record.diff
    assert file_change_action_label(record) == "Edited"


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


def test_insert_lines_produces_diff(tmp_path: Path) -> None:
    """Tracked insert_lines shows a unified diff after the tool result."""
    target = tmp_path / "insert.txt"
    target.write_text("line1\nline3\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "insert_lines",
        {"file_path": str(target), "line": 2, "content": "line2\n"},
        "tc-ins",
    )

    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-ins", content="ok", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "+line2" in record.diff
    assert file_change_action_label(record) == "Inserted"


def test_delete_lines_produces_diff(tmp_path: Path) -> None:
    """Tracked delete_lines shows removed lines in the unified diff."""
    target = tmp_path / "delete_lines.txt"
    target.write_text("keep\nremove\nkeep2\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "delete_lines",
        {"file_path": str(target), "start_line": 2, "end_line": 2},
        "tc-dlines",
    )

    target.write_text("keep\nkeep2\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-dlines", content="ok", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "-remove" in record.diff
    assert file_change_action_label(record) == "Deleted"


def test_apply_diff_produces_diff(tmp_path: Path) -> None:
    """Tracked apply_diff reflects on-disk before/after content."""
    target = tmp_path / "patch.py"
    target.write_text("print('old')\n", encoding="utf-8")
    patch = """--- patch.py
+++ patch.py
@@ -1 +1 @@
-print('old')
+print('new')
"""
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "apply_diff",
        {"file_path": str(target), "diff": patch},
        "tc-patch",
    )

    target.write_text("print('new')\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(tool_call_id="tc-patch", content="ok", status="success")
    )

    assert record is not None
    assert record.diff is not None
    assert "-print('old')" in record.diff
    assert "+print('new')" in record.diff
    assert file_change_action_label(record) == "Patched"


def test_edit_file_completes_with_provider_call_id_alias(tmp_path: Path) -> None:
    """Stream-predicted id can complete when ToolMessage uses opaque call_* id."""
    target = tmp_path / "baidu.go"
    target.write_text("before\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    predicted_id = "VSX_07:s:edit_file:0"
    provider_id = "VSX_07:s:call_f4315f7a2e5a41f9aba59674"
    track_file_operation(
        tracker,
        "edit_file",
        {
            "file_path": str(target),
            "old_string": "before",
            "new_string": "after",
        },
        predicted_id,
    )

    target.write_text("after\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(
            tool_call_id=provider_id,
            name="edit_file",
            content=f"Successfully replaced 1 instance(s) in '{target}'",
            status="success",
        )
    )

    assert record is not None
    assert predicted_id not in tracker.active
    assert record.diff is not None
    assert "-before" in record.diff
    assert "+after" in record.diff


def test_edit_file_alias_requires_unique_match_when_multiple_pending(tmp_path: Path) -> None:
    """Ambiguous alias candidates without path disambiguation do not complete."""
    file_a = tmp_path / "a.go"
    file_b = tmp_path / "b.go"
    file_a.write_text("a\n", encoding="utf-8")
    file_b.write_text("b\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "edit_file",
        {"file_path": str(file_a), "old_string": "a", "new_string": "A"},
        "VSX_07:s:edit_file:0",
    )
    track_file_operation(
        tracker,
        "edit_file",
        {"file_path": str(file_b), "old_string": "b", "new_string": "B"},
        "VSX_07:s:edit_file:1",
    )

    record = tracker.complete_with_message(
        SimpleNamespace(
            tool_call_id="VSX_07:s:call_abc123",
            name="edit_file",
            content="ok",
            status="success",
        )
    )

    assert record is None
    assert len(tracker.active) == 2


def test_stash_untracked_edit_result_and_skip_late_track(tmp_path: Path) -> None:
    """Early ToolMessage is stashed; late track must not capture post-edit before."""
    target = tmp_path / "e2e.py"
    target.write_text("after\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    tcid = "JPI_02:s:call_aabbcc"

    msg = SimpleNamespace(
        tool_call_id=tcid,
        name="edit_file",
        content=f"Successfully replaced 1 instance(s) of the string in '{target}'",
        status="success",
    )
    assert tracker.complete_with_message(msg) is None
    record = tracker.stash_untracked_file_change_result(msg)
    assert record is not None
    assert record.after_content == "after\n"
    assert tracker.recently_completed[tcid] is record

    track_file_operation(
        tracker,
        "edit_file",
        {
            "file_path": str(target),
            "old_string": "before",
            "new_string": "after",
        },
        tcid,
    )
    assert tcid not in tracker.active
    assert tracker.peek_recently_completed(tcid, tool_name="edit_file") is record


def test_complete_with_message_populates_recently_completed(tmp_path: Path) -> None:
    """Normal completions are available for late-mount lookups."""
    target = tmp_path / "x.txt"
    target.write_text("old\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    track_file_operation(
        tracker,
        "edit_file",
        {"file_path": str(target), "old_string": "old", "new_string": "new"},
        "tc-1",
    )
    target.write_text("new\n", encoding="utf-8")
    record = tracker.complete_with_message(
        SimpleNamespace(
            tool_call_id="tc-1",
            name="edit_file",
            content=f"Successfully replaced 1 instance(s) in '{target}'",
            status="success",
        )
    )
    assert record is not None
    assert tracker.peek_recently_completed("tc-1", tool_name="edit_file") is record
    taken = tracker.take_recently_completed("tc-1", tool_name="edit_file")
    assert taken is record
    assert tracker.peek_recently_completed("tc-1", tool_name="edit_file") is None
