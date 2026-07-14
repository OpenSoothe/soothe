"""Tests for non-blocking filesystem change preview widgets."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.tools.metadata import get_file_write_tool_names

from soothe_cli.runtime.state.file_tracker import (
    FILE_CHANGE_TOOLS,
    FileOperationRecord,
    FileOpMetrics,
    apply_edit_file_lines_to_content,
    apply_insert_lines_to_content,
    extract_line_range_text,
    file_change_action_label,
    file_change_label,
    file_change_label_from_preview_data,
)
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.file_change_notify import (
    finalize_file_change_preview,
    handle_file_change_result_without_active_track,
    mount_file_change_preview,
    textual_widget_id,
)
from soothe_cli.tui.file_change_renderers import (
    build_file_change_preview,
    update_preview_data_from_record,
)
from soothe_cli.tui.widgets.file_change_preview import (
    DeleteFilePreviewWidget,
    EditFileLinesPreviewWidget,
    EditFilePreviewWidget,
    FileChangePreviewWidget,
    InsertLinesPreviewWidget,
    WriteFilePreviewWidget,
)
from soothe_cli.tui.widgets.messages.diff_message import DiffMessage


def test_file_change_tools_match_metadata_registry() -> None:
    """TUI file-change previews cover every file_write tool in metadata."""
    assert FILE_CHANGE_TOOLS == get_file_write_tool_names()


def test_file_change_labels_support_pending_and_success_tense() -> None:
    """File cards use progressive labels while running and past tense when done."""
    assert file_change_label("write_file", phase="pending") == "Writing"
    assert file_change_label("write_file", is_new_file=True, phase="pending") == "Creating"
    assert file_change_label("edit_file", phase="pending") == "Editing"
    assert file_change_label("edit_file_lines", phase="pending") == "Editing"
    assert file_change_label("insert_lines", phase="pending") == "Inserting"
    assert file_change_label("delete_lines", phase="pending") == "Deleting"
    assert file_change_label("apply_diff", phase="pending") == "Patching"
    assert file_change_label("delete_file", phase="pending") == "Deleting"
    assert file_change_label("unknown_tool", phase="pending") == "Changing"

    assert file_change_label("write_file") == "Written"
    assert file_change_label("write_file", is_new_file=True) == "Created"
    assert file_change_label("edit_file") == "Edited"
    assert file_change_label("edit_file_lines") == "Edited"
    assert file_change_label("insert_lines") == "Inserted"
    assert file_change_label("delete_lines") == "Deleted"
    assert file_change_label("apply_diff") == "Patched"
    assert file_change_label("delete_file") == "Deleted"
    assert file_change_label("unknown_tool") == "Changed"
    assert (
        file_change_label_from_preview_data(
            "write_file",
            {"is_new_file": True},
        )
        == "Creating"
    )


def test_file_change_preview_uses_stream_card_bottom_margin() -> None:
    """File edit cards match cognition/assistant inter-card spacing (RFC-501 §10.3)."""
    assert "margin: 0 0 1 0;" in FileChangePreviewWidget.DEFAULT_CSS
    assert "margin: 0 0 1 0;" in DiffMessage.DEFAULT_CSS


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


def test_write_file_preview_starts_expanded() -> None:
    """In-flight file previews default to expanded diff/content view."""
    widget = WriteFilePreviewWidget(
        {"file_path": "src/a.py", "content": "hello", "is_new_file": True},
        action_label="Created",
    )
    assert widget.is_expanded is True
    widget.toggle_expand()
    assert widget.is_expanded is False
    assert widget.has_class("-collapsed")
    widget.toggle_expand()
    assert widget.is_expanded is True
    assert widget.has_class("-expanded")


def test_write_file_preview_compose_includes_header_and_body() -> None:
    """Expanded compose still includes header and diff/content children."""
    widget = WriteFilePreviewWidget(
        {"file_path": "src/a.py", "content": "line1\nline2", "is_new_file": True},
        action_label="Created",
    )
    children = list(widget.compose())
    classes = [c for child in children for c in (getattr(child, "classes", None) or set())]
    assert "file-change-preview-header" in classes
    assert "diff-line-added" in classes or "file-change-preview-body" in classes


@pytest.mark.asyncio
async def test_finalize_collapses_preview_after_completion() -> None:
    """Finalizing on-disk results collapses the preview card."""
    widget = WriteFilePreviewWidget(
        {"file_path": "/tmp/x.txt", "content": "draft", "is_new_file": True},
        action_label="Created",
    )
    widget._expanded = True
    widget._finalized = False
    record = FileOperationRecord(
        tool_name="write_file",
        display_path="/tmp/x.txt",
        physical_path=None,
        tool_call_id="tc-1",
        before_content="",
        after_content="final",
        metrics=FileOpMetrics(lines_written=1),
    )
    await widget.finalize_from_record(record)
    assert widget._finalized is True
    assert widget.is_expanded is False


def test_write_file_overwrite_diff_compose_renders_diff_lines(tmp_path: Path) -> None:
    """Regression: overwrite preview uses compact gutter-bar style (diff-line-* classes)."""
    target = tmp_path / "existing.txt"
    target.write_text("old\n", encoding="utf-8")
    built = build_file_change_preview(
        "write_file",
        {"file_path": str(target), "content": "new\n"},
        assistant_id=None,
    )
    assert built is not None
    _, data = built
    widget = WriteFilePreviewWidget(data)
    children = list(widget.compose())
    assert children
    classes = {getattr(c, "classes", None) for c in children}
    # Updated to match compact gutter-bar style (diff-line-removed/diff-line-added)
    assert frozenset({"diff-line-removed", "diff-line-added"}) & {
        cls for group in classes if group for cls in group
    }


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


def test_edit_file_preview_diff_rows_align_context_and_additions() -> None:
    """Regression: added lines must align with context lines in diff previews."""
    from soothe_cli.tui.widgets.diff import format_diff_row_plain

    width = 3
    content = "        if self._autopilot is not None:"
    context = format_diff_row_plain(" ", content, line_num=92, width=width)
    added = format_diff_row_plain("+", content, line_num=96, width=width)
    assert context.index(content) == added.index(content)


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


def test_build_insert_lines_preview_shows_file_diff(tmp_path: Path) -> None:
    """insert_lines preview diffs the file before and after insertion."""
    target = tmp_path / "doc.md"
    target.write_text("# Title\n\nBody\n", encoding="utf-8")
    frontmatter = "---\ntitle: Doc\n---\n\n"
    built = build_file_change_preview(
        "insert_lines",
        {"file_path": str(target), "line": 1, "content": frontmatter},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is InsertLinesPreviewWidget
    assert data["insert_line"] == 1
    assert any(line.startswith("+") for line in data["diff_lines"])

    after = apply_insert_lines_to_content(target.read_text(encoding="utf-8"), 1, frontmatter)
    assert after is not None
    assert after.startswith("---")


def test_build_delete_lines_preview_shows_removed_lines(tmp_path: Path) -> None:
    """delete_lines preview shows a unified diff with deletions."""
    target = tmp_path / "doc.md"
    target.write_text("keep\nremove\nkeep2\n", encoding="utf-8")
    built = build_file_change_preview(
        "delete_lines",
        {"file_path": str(target), "start_line": 2, "end_line": 2},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is EditFileLinesPreviewWidget
    assert "-remove" in "".join(data["diff_lines"])


def test_build_apply_diff_preview_shows_patch(tmp_path: Path) -> None:
    """apply_diff preview renders the patch body."""
    target = tmp_path / "a.py"
    target.write_text("print('old')\n", encoding="utf-8")
    patch = """--- a.py
+++ a.py
@@ -1 +1 @@
-print('old')
+print('new')
"""
    built = build_file_change_preview(
        "apply_diff",
        {"file_path": str(target), "diff": patch},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built
    assert cls is EditFilePreviewWidget
    assert "-print('old')" in "".join(data["diff_lines"])


def test_file_change_action_label_for_surgical_tools() -> None:
    """Surgical file tools get distinct completed labels."""
    assert (
        file_change_action_label(
            FileOperationRecord(
                tool_name="insert_lines",
                display_path="a.md",
                physical_path=None,
                tool_call_id="tc-1",
            )
        )
        == "Inserted"
    )
    assert (
        file_change_action_label(
            FileOperationRecord(
                tool_name="apply_diff",
                display_path="a.py",
                physical_path=None,
                tool_call_id="tc-2",
            )
        )
        == "Patched"
    )


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
async def test_mount_renders_expanded_preview_body() -> None:
    """In-flight preview mounts in expanded mode with visible header/body."""
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll

    built = build_file_change_preview(
        "edit_file",
        {"file_path": "src/a.py", "old_string": "foo", "new_string": "bar"},
        assistant_id=None,
    )
    assert built is not None
    cls, data = built

    class PreviewApp(App):
        def compose(self) -> ComposeResult:
            yield VerticalScroll(cls(data, action_label="Editing"))

    app = PreviewApp()
    async with app.run_test(size=(100, 10)):
        widget = app.query_one(cls)
        header = app.query_one(".file-change-preview-header")
        assert widget.has_class("-expanded")
        assert widget.size.height >= 1
        assert header.size.height >= 1
        rendered = str(header.render())
        assert get_glyphs().file_edit_prefix in rendered
        assert "Editing" in rendered
        assert "src/a.py" in rendered


@pytest.mark.asyncio
async def test_mount_file_change_preview_accepts_unified_tool_call_id() -> None:
    """Mount succeeds when tool_call_id contains colons (unified id format)."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
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
    assert adapter._file_change_widgets["JWZ_01:s:write_file:23"] is mounted


@pytest.mark.asyncio
async def test_finalize_file_change_preview_upgrades_mounted_widget() -> None:
    """Completion finalizes the preview card instead of mounting a second diff."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
    adapter._mount_message = AsyncMock()

    args = {"file_path": "/tmp/x.txt", "content": "hello"}
    await mount_file_change_preview(
        adapter,
        tool_name="write_file",
        args=args,
        tool_call_id="tc-1",
        assistant_id=None,
    )
    widget = adapter._file_change_widgets["tc-1"]
    assert widget._action_label == "Creating"

    record = FileOperationRecord(
        tool_name="write_file",
        display_path="/tmp/x.txt",
        physical_path=None,
        tool_call_id="tc-1",
        before_content="",
        after_content="hello",
        metrics=FileOpMetrics(lines_written=1),
    )
    handled = await finalize_file_change_preview(adapter, record=record)

    assert handled is True
    assert widget._finalized is True
    assert widget._action_label == file_change_action_label(record)


def test_update_preview_data_from_record_write_file_new() -> None:
    data = {"file_path": "/tmp/x.txt", "content": "draft", "is_new_file": True}
    record = FileOperationRecord(
        tool_name="write_file",
        display_path="/tmp/x.txt",
        physical_path=None,
        tool_call_id="tc-1",
        before_content="",
        after_content="final",
    )
    update_preview_data_from_record(data, record)
    assert data["content"] == "final"
    assert data["is_new_file"] is True
    assert "diff_lines" not in data


@pytest.mark.asyncio
async def test_finalize_file_change_preview_returns_false_without_widget() -> None:
    adapter = MagicMock()
    adapter._file_change_widgets = {}
    record = FileOperationRecord(
        tool_name="edit_file",
        display_path="a.py",
        physical_path=None,
        tool_call_id="missing",
        diff="-foo\n+bar",
    )
    assert await finalize_file_change_preview(adapter, record=record) is False


@pytest.mark.asyncio
async def test_mount_file_change_preview_dedupes_by_tool_call_id() -> None:
    """Only one preview card is mounted per tool_call_id per turn."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
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


@pytest.mark.asyncio
async def test_finalize_file_change_preview_resolves_provider_call_id_alias() -> None:
    """Finalize finds a widget mounted under a stream-predicted id alias."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
    adapter._mount_message = AsyncMock()

    args = {
        "file_path": "/tmp/baidu.go",
        "old_string": "before",
        "new_string": "after",
    }
    await mount_file_change_preview(
        adapter,
        tool_name="edit_file",
        args=args,
        tool_call_id="VSX_07:s:edit_file:0",
        assistant_id=None,
    )
    widget = adapter._file_change_widgets["VSX_07:s:edit_file:0"]
    assert widget._action_label == "Editing"

    record = FileOperationRecord(
        tool_name="edit_file",
        display_path="/tmp/baidu.go",
        physical_path=None,
        tool_call_id="VSX_07:s:call_f4315f7a2e5a41f9aba59674",
        before_content="before",
        after_content="after",
    )
    handled = await finalize_file_change_preview(adapter, record=record)

    assert handled is True
    assert widget._finalized is True
    assert widget._action_label == "Edited"


@pytest.mark.asyncio
async def test_mount_file_change_preview_skips_alias_duplicate() -> None:
    """Wire/provider ids do not mount a second card when stream id already exists."""
    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
    adapter._mount_message = AsyncMock()

    args = {
        "file_path": "/tmp/baidu.go",
        "old_string": "before",
        "new_string": "after",
    }
    await mount_file_change_preview(
        adapter,
        tool_name="edit_file",
        args=args,
        tool_call_id="VSX_07:s:edit_file:0",
        assistant_id=None,
    )
    await mount_file_change_preview(
        adapter,
        tool_name="edit_file",
        args=args,
        tool_call_id="VSX_07:s:call_f4315f7a2e5a41f9aba59674",
        assistant_id=None,
    )

    assert adapter._mount_message.await_count == 1
    assert len(adapter._file_change_widgets) == 1


@pytest.mark.asyncio
async def test_mount_late_after_early_result_shows_edited(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Result-before-preview race mounts as Edited, not a stuck Editing card."""
    from soothe_cli.runtime.state.file_tracker import FileOpTracker

    target = tmp_path / "e2e.py"
    target.write_text("after\n", encoding="utf-8")
    tracker = FileOpTracker(assistant_id=None)
    tcid = "JPI_02:s:call_8ee18d9179724fc19a79dd63"

    msg = SimpleNamespace(
        tool_call_id=tcid,
        name="edit_file",
        content=f"Successfully replaced 1 instance(s) of the string in '{target}'",
        status="success",
    )
    assert tracker.complete_with_message(msg) is None
    with caplog.at_level(logging.DEBUG, logger="soothe_cli.tui.file_change_notify"):
        stashed = handle_file_change_result_without_active_track(
            tracker,
            msg,
            tool_name="edit_file",
            tool_call_id=tcid,
        )
    assert stashed is not None
    assert stashed.status == "success"
    assert "result-before-preview race" in caplog.text
    assert tcid in caplog.text

    adapter = MagicMock()
    adapter._file_change_previews_shown = set()
    adapter._file_change_widgets = {}
    adapter._mount_message = AsyncMock()

    await mount_file_change_preview(
        adapter,
        tool_name="edit_file",
        args={
            "file_path": str(target),
            "old_string": "before",
            "new_string": "after",
        },
        tool_call_id=tcid,
        assistant_id=None,
        file_op_tracker=tracker,
    )

    assert adapter._mount_message.await_count == 1
    widget = adapter._file_change_widgets[tcid]
    assert widget._action_label == "Edited"
    assert widget._finalized is True
    assert tracker.peek_recently_completed(tcid, tool_name="edit_file") is None
