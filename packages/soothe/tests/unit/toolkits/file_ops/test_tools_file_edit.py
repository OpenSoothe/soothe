"""Tests for File Ops tools functionality.

Tests surgical file operations provided by soothe.toolkits.file_ops:
- delete_file: Delete files with optional backup
- file_info: Get file metadata
- edit_file_lines: Replace specific line ranges
- insert_lines: Insert content at specific line
- delete_lines: Delete specific line ranges
- apply_diff: Apply unified diff patches

Note: This toolkit does NOT provide read_file, write_file, search_files, list_files
(those are provided by deepagents FilesystemMiddleware).
"""

import asyncio
import platform
import tempfile
import warnings
from pathlib import Path

import pytest

from soothe.toolkits._internal.file_edit import (
    _detect_stripped_absolute_path,
)
from soothe.toolkits.file_ops import (
    ApplyDiffTool,
    DeleteFileTool,
    DeleteLinesTool,
    EditFileLinesTool,
    FileInfoTool,
    InsertLinesTool,
)


class TestDeleteFileTool:
    """Test DeleteFileTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = DeleteFileTool()

        assert tool.name == "delete_file"
        assert "delete" in tool.description.lower()

    def test_delete_existing_file(self) -> None:
        """Test deleting an existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = DeleteFileTool(work_dir=temp_dir, backup_enabled=False)

            result = tool._run("test.txt")

            assert "Deleted:" in result
            assert not file_path.exists()

    def test_delete_nonexistent_file(self) -> None:
        """Test deleting a non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = DeleteFileTool(work_dir=temp_dir)

            result = tool._run("nonexistent.txt")

            assert "Error" in result
            assert "not found" in result.lower()

    def test_delete_with_backup(self) -> None:
        """Test deleting file with backup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = DeleteFileTool(work_dir=temp_dir, backup_enabled=True)

            result = tool._run("test.txt")

            assert "backup:" in result.lower()

    def test_async_delete_honors_backup_keyword(self) -> None:
        """Async wrapper should work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")
            tool = DeleteFileTool(work_dir=temp_dir, backup_enabled=False)

            result = asyncio.run(tool._arun("test.txt"))

            assert "Deleted:" in result
            assert not file_path.exists()


class TestFileInfoTool:
    """Test FileInfoTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = FileInfoTool()

        assert tool.name == "file_info"
        assert "info" in tool.description.lower() or "metadata" in tool.description.lower()

    def test_get_file_info(self) -> None:
        """Test getting file info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = FileInfoTool(work_dir=temp_dir)

            result = tool._run("test.txt")

            assert "Path:" in result
            assert "Size:" in result
            assert "Modified:" in result

    def test_get_nonexistent_file_info(self) -> None:
        """Test getting info for non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = FileInfoTool(work_dir=temp_dir)

            result = tool._run("nonexistent.txt")

            assert "Error" in result
            assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Surgical Code Editing Tools (merged from code_edit toolkit)
# ---------------------------------------------------------------------------


class TestEditFileLinesTool:
    """Tests for edit_file_lines tool."""

    def test_replace_single_line(self) -> None:
        """Test replacing a single line."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            result = tool._run(path=f.name, start_line=2, end_line=2, new_content="modified_line2")

            assert "Updated" in result
            assert "1 removed, 1 added" in result

            with open(f.name) as rf:
                content = rf.read()
                assert "modified_line2" in content
                assert "line1" in content
                assert "line3" in content

            Path(f.name).unlink()

    def test_replace_multiple_lines(self) -> None:
        """Test replacing multiple lines."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
            f.flush()

            result = tool._run(
                path=f.name, start_line=2, end_line=4, new_content="new2\nnew3\nnew4"
            )

            assert "Updated" in result
            assert "3 removed, 3 added" in result

            with open(f.name) as rf:
                content = rf.read()
                assert "line1" in content
                assert "new2" in content
                assert "new3" in content
                assert "new4" in content
                assert "line5" in content

            Path(f.name).unlink()

    def test_replace_with_different_line_count(self) -> None:
        """Test replacing with different number of lines."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            result = tool._run(
                path=f.name, start_line=2, end_line=3, new_content="new1\nnew2\nnew3\nnew4"
            )

            assert "2 removed, 4 added" in result

            with open(f.name) as rf:
                lines = rf.readlines()
                assert len(lines) == 5

            Path(f.name).unlink()

    def test_invalid_line_range(self) -> None:
        """Test error handling for invalid line range."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            result = tool._run(path=f.name, start_line=5, end_line=6, new_content="x")
            assert "Error" in result
            assert "Invalid start_line" in result

            result = tool._run(path=f.name, start_line=1, end_line=5, new_content="x")
            assert "Error" in result
            assert "Invalid end_line" in result

            Path(f.name).unlink()

    def test_file_not_found(self) -> None:
        """Test error handling for missing file."""
        tool = EditFileLinesTool()

        result = tool._run(path="/nonexistent/file.py", start_line=1, end_line=1, new_content="x")
        assert "Error" in result
        assert "File not found" in result


class TestInsertLinesTool:
    """Tests for insert_lines tool."""

    def test_insert_at_beginning(self) -> None:
        """Test inserting at beginning of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            tool._run(path=f.name, line=1, content="new_first")

            with open(f.name) as rf:
                lines = rf.readlines()
                assert lines[0] == "new_first\n"
                assert lines[1] == "line1\n"

            Path(f.name).unlink()

    def test_insert_in_middle(self) -> None:
        """Test inserting in middle of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            tool._run(path=f.name, line=2, content="inserted")

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\ninserted\nline2\nline3\n"

            Path(f.name).unlink()

    def test_insert_at_end(self) -> None:
        """Test appending at end of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            tool._run(path=f.name, line=3, content="new_last")

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline2\nnew_last\n"

            Path(f.name).unlink()


class TestDeleteLinesTool:
    """Tests for delete_lines tool."""

    def test_delete_single_line(self) -> None:
        """Test deleting a single line."""
        tool = DeleteLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            tool._run(path=f.name, start_line=2, end_line=2)

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline3\n"

            Path(f.name).unlink()

    def test_delete_multiple_lines(self) -> None:
        """Test deleting multiple lines."""
        tool = DeleteLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
            f.flush()

            tool._run(path=f.name, start_line=2, end_line=4)

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline5\n"

            Path(f.name).unlink()


class TestApplyDiffTool:
    """Tests for apply_diff tool."""

    def test_apply_simple_diff(self) -> None:
        """Test applying a simple diff."""
        tool = ApplyDiffTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("def hello():\n    print('world')\n")
            f.flush()

            diff = f"""--- {f.name}
+++ {f.name}
@@ -1,2 +1,2 @@
 def hello():
-    print('world')
+    print('hello')
"""

            tool._run(path=f.name, diff=diff)

            with open(f.name) as rf:
                content = rf.read()
                assert "print('hello')" in content
                assert "print('world')" not in content

            Path(f.name).unlink()

    def test_apply_diff_file_not_found(self) -> None:
        """Test applying diff to non-existent file."""
        tool = ApplyDiffTool()

        diff = "--- /nonexistent/file.py\n+++ /nonexistent/file.py\n@@ -1 +1 @@\n-old\n+new\n"
        result = tool._run(path="/nonexistent/file.py", diff=diff)

        assert "Error" in result
        assert "File not found" in result


class TestStrippedAbsolutePathDetection:
    """Test detection and correction of stripped absolute paths."""

    def test_detect_stripped_home_directory_path_macos(self) -> None:
        """Test detection of stripped macOS home directory paths."""
        if platform.system() != "Darwin":
            pytest.skip("macOS only")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            result = _detect_stripped_absolute_path("Users/john/report.md")
            assert result == "/Users/john/report.md"
            assert len(w) == 1
            assert "stripped absolute path" in str(w[0].message).lower()

    def test_detect_stripped_home_directory_path_linux(self) -> None:
        """Test detection of stripped Linux home directory paths."""
        if platform.system() != "Linux":
            pytest.skip("Linux only")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            result = _detect_stripped_absolute_path("home/john/report.md")
            assert result == "/home/john/report.md"
            assert len(w) == 1
            assert "stripped absolute path" in str(w[0].message).lower()

    def test_normal_relative_path_not_detected(self) -> None:
        """Normal relative paths should not trigger detection."""
        result = _detect_stripped_absolute_path("output/report.md")
        assert result is None

        result = _detect_stripped_absolute_path("src/utils/helper.py")
        assert result is None

    def test_already_absolute_path_not_detected(self) -> None:
        """Already absolute paths should not trigger detection."""
        result = _detect_stripped_absolute_path("/Users/john/report.md")
        assert result is None

        result = _detect_stripped_absolute_path("/home/john/report.md")
        assert result is None
