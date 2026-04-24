"""Integration tests for file operation tools.

Tests surgical file manipulation tools from soothe.toolkits.file_ops:
- delete_file: Delete files with optional backup
- file_info: Get file metadata
- edit_file_lines: Replace specific line range in a file
- insert_lines: Insert content at a specific line
- delete_lines: Delete specific line range from a file
- apply_diff: Apply a unified diff patch to a file

Note: Basic file operations (read_file, write_file, search_files, list_files) are
provided by deepagents' FilesystemMiddleware, not this module.
"""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Delete File Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteFileTool:
    """Integration tests for DeleteFileTool."""

    @pytest.fixture
    def delete_tool(self):
        """Create DeleteFileTool instance."""
        from soothe.toolkits.file_ops import DeleteFileTool

        return DeleteFileTool()

    def test_delete_existing_file(self, delete_tool) -> None:
        """Test deleting an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "delete_me.txt"
            test_file.write_text("content")

            result = delete_tool._run(str(test_file))

            assert not test_file.exists()
            assert "Deleted" in result

    def test_delete_nonexistent_file(self, delete_tool) -> None:
        """Test deleting non-existent file."""
        result = delete_tool._run("/nonexistent/file.txt")

        # Should return error message
        assert "Error" in result or "not found" in result.lower()

    def test_delete_with_backup(self, delete_tool) -> None:
        """Test deletion creates backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "backup_test.txt"
            test_file.write_text("important content")

            delete_tool.backup_enabled = True
            delete_tool.backup_dir = tmpdir
            result = delete_tool._run(str(test_file))

            assert not test_file.exists()
            assert "backup" in result.lower()


# ---------------------------------------------------------------------------
# File Info Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFileInfoTool:
    """Integration tests for FileInfoTool."""

    @pytest.fixture
    def info_tool(self):
        """Create FileInfoTool instance."""
        from soothe.toolkits.file_ops import FileInfoTool

        return FileInfoTool()

    def test_get_file_metadata(self, info_tool) -> None:
        """Test getting file metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            result = info_tool._run(str(test_file))

            # Should return file metadata
            assert "Path:" in result
            assert "Size:" in result
            assert "Modified:" in result

    def test_get_nonexistent_file_info(self, info_tool) -> None:
        """Test getting info for non-existent file."""
        result = info_tool._run("/nonexistent/file.txt")

        # Should handle gracefully
        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# Edit File Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEditFileLinesTool:
    """Integration tests for EditFileLinesTool."""

    @pytest.fixture
    def edit_tool(self):
        """Create EditFileLinesTool instance."""
        from soothe.toolkits.file_ops import EditFileLinesTool

        return EditFileLinesTool()

    def test_replace_lines(self, edit_tool) -> None:
        """Test replacing specific line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            lines = [f"Line {i}" for i in range(1, 11)]
            test_file.write_text("\n".join(lines))

            result = edit_tool._run(
                str(test_file),
                start_line=3,
                end_line=5,
                new_content="New Line 3\nNew Line 4\nNew Line 5",
            )

            content = test_file.read_text()
            assert "New Line 3" in content
            assert "Line 6" in content  # Line after replaced range should still exist
            assert "Line 2" in content  # Line before replaced range should still exist
            assert "Updated" in result

    def test_edit_nonexistent_file(self, edit_tool) -> None:
        """Test editing non-existent file."""
        result = edit_tool._run(
            "/nonexistent/file.txt", start_line=1, end_line=2, new_content="test"
        )

        assert "Error" in result or "not found" in result.lower()

    def test_invalid_line_range(self, edit_tool) -> None:
        """Test invalid line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Line 1\nLine 2")

            result = edit_tool._run(str(test_file), start_line=10, end_line=15, new_content="test")

            assert "Error" in result or "Invalid" in result


# ---------------------------------------------------------------------------
# Insert Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsertLinesTool:
    """Integration tests for InsertLinesTool."""

    @pytest.fixture
    def insert_tool(self):
        """Create InsertLinesTool instance."""
        from soothe.toolkits.file_ops import InsertLinesTool

        return InsertLinesTool()

    def test_insert_at_line(self, insert_tool) -> None:
        """Test inserting content at specific line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("Line 1\nLine 2\nLine 3")

            result = insert_tool._run(str(test_file), line=2, content="Inserted Line")

            content = test_file.read_text()
            lines = content.splitlines()
            assert "Inserted Line" in lines[1]  # Should be at line 2
            assert "Line 1" in lines[0]
            assert "Inserted" in result

    def test_insert_at_end(self, insert_tool) -> None:
        """Test inserting at end of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Line 1\nLine 2")

            _ = insert_tool._run(str(test_file), line=3, content="Final Line")

            content = test_file.read_text()
            assert "Final Line" in content


# ---------------------------------------------------------------------------
# Delete Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteLinesTool:
    """Integration tests for DeleteLinesTool."""

    @pytest.fixture
    def delete_lines_tool(self):
        """Create DeleteLinesTool instance."""
        from soothe.toolkits.file_ops import DeleteLinesTool

        return DeleteLinesTool()

    def test_delete_line_range(self, delete_lines_tool) -> None:
        """Test deleting specific line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            lines = [f"Line {i}" for i in range(1, 11)]
            test_file.write_text("\n".join(lines))

            result = delete_lines_tool._run(str(test_file), start_line=3, end_line=5)

            content = test_file.read_text()
            assert "Line 3" not in content
            assert "Line 5" not in content
            assert "Line 6" in content  # Line after deleted range
            assert "Deleted" in result

    def test_delete_invalid_range(self, delete_lines_tool) -> None:
        """Test deleting invalid line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Line 1\nLine 2")

            result = delete_lines_tool._run(str(test_file), start_line=10, end_line=15)

            assert "Error" in result or "Invalid" in result


# ---------------------------------------------------------------------------
# Apply Diff Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestApplyDiffTool:
    """Integration tests for ApplyDiffTool."""

    @pytest.fixture
    def apply_diff_tool(self):
        """Create ApplyDiffTool instance."""
        from soothe.toolkits.file_ops import ApplyDiffTool

        return ApplyDiffTool()

    def test_apply_simple_diff(self, apply_diff_tool) -> None:
        """Test applying a simple unified diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Original content\n")

            diff = "--- test.txt\n+++ test.txt\n@@ -1 +1 @@\n-Original content\n+Modified content\n"

            result = apply_diff_tool._run(str(test_file), diff=diff)

            content = test_file.read_text()
            assert "Modified content" in content
            assert "Applied" in result

    def test_apply_invalid_diff(self, apply_diff_tool) -> None:
        """Test applying invalid diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            result = apply_diff_tool._run(str(test_file), diff="invalid diff format")

            assert "Error" in result or "Failed" in result


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFileOpsErrorHandling:
    """Test error handling across file operation tools."""

    def test_permission_errors(self) -> None:
        """Test handling of file permission errors."""
        # Would need specific setup to test permission errors
        pytest.skip("Requires specific file permission setup")

    def test_disk_full_handling(self) -> None:
        """Test handling of disk full errors."""
        pytest.skip("Requires specific disk space setup")

    def test_concurrent_file_access(self) -> None:
        """Test handling of concurrent file operations."""
        pytest.skip("Requires concurrent execution setup")
