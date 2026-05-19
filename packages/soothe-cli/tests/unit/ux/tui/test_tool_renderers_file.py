"""Tests for file tool approval renderers."""

from __future__ import annotations

from pathlib import Path

from soothe_cli.tui.widgets.tool_renderers import (
    DeleteFileRenderer,
    WriteFileRenderer,
)
from soothe_cli.tui.widgets.tool_widgets import (
    DeleteFileApprovalWidget,
    WriteFileApprovalWidget,
)


def test_write_file_renderer_marks_new_file(tmp_path: Path, monkeypatch) -> None:
    """New paths are flagged for the write approval widget."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "brand_new.py"
    widget_cls, data = WriteFileRenderer.get_approval_widget(
        {"file_path": str(path), "content": "print('hi')\n"}
    )
    assert widget_cls is WriteFileApprovalWidget
    assert data["is_new_file"] is True


def test_delete_file_renderer_includes_preview(tmp_path: Path, monkeypatch) -> None:
    """Delete renderer reads a short preview from disk."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "old.txt"
    path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    widget_cls, data = DeleteFileRenderer.get_approval_widget({"file_path": str(path)})
    assert widget_cls is DeleteFileApprovalWidget
    assert data["preview_lines"] == ["line1", "line2", "line3"]
    assert data["total_lines"] == 3
