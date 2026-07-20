"""Integration tests for file operation tools.

Tests surgical file manipulation tools from soothe_nano.toolkits.file_ops:
- delete: Delete files/directories with optional backup
- file_info: Get file metadata
- edit_lines: Replace specific line range in a file
- insert_lines: Insert content at a specific line
- delete_lines: Delete specific line range from a file
- apply_diff: Apply a unified diff patch to a file

Note: Basic file operations (read_file, write_file, search_files, list_files) are
provided by soothe_deepagents' FilesystemMiddleware, not this module.
"""

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Middleware Fixture (Reference Implementation)
# ---------------------------------------------------------------------------


@pytest.fixture
def middleware(tmp_path):
    """Create SootheFilesystemMiddleware for testing.

    This is the reference pattern for testing file_ops tools.
    """
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

    backend = FilesystemBackend(root_dir=tmp_path)
    return SootheFilesystemMiddleware(
        backend=backend,
        backup_enabled=True,
        backup_dir=str(tmp_path / ".backups"),
    )


@pytest.fixture
def delete_tool(middleware):
    """Get delete tool from middleware."""
    return next(t for t in middleware.tools if t.name == "delete")


@pytest.fixture
def info_tool(middleware):
    """Get file_info tool from middleware."""
    return next(t for t in middleware.tools if t.name == "file_info")


@pytest.fixture
def edit_tool(middleware):
    """Get edit_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "edit_lines")


@pytest.fixture
def insert_tool(middleware):
    """Get insert_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "insert_lines")


@pytest.fixture
def delete_lines_tool(middleware):
    """Get delete_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "delete_lines")


@pytest.fixture
def apply_diff_tool(middleware):
    """Get apply_diff tool from middleware."""
    return next(t for t in middleware.tools if t.name == "apply_diff")


# ---------------------------------------------------------------------------
# Delete File Tool Tests
# ---------------------------------------------------------------------------


class TestDeleteFileTool:
    """Integration tests for delete tool."""

    def test_delete_existing_file(self, delete_tool, tmp_path) -> None:
        """Test deleting an existing file."""
        test_file = tmp_path / "delete_me.txt"
        test_file.write_text("content")

        result = delete_tool.invoke({"file_path": str(test_file), "backup": True})

        assert not test_file.exists()
        assert "Deleted" in result or "deleted" in result.lower()

    def test_delete_nonexistent_file(self, delete_tool) -> None:
        """Test deleting non-existent file."""
        result = delete_tool.invoke({"file_path": "/nonexistent/file.txt"})

        # Should return error message
        assert "Error" in result or "not found" in result.lower()

    def test_delete_with_backup(self, delete_tool, tmp_path) -> None:
        """Test deletion creates backup."""
        test_file = tmp_path / "backup_test.txt"
        test_file.write_text("important content")

        result = delete_tool.invoke({"file_path": str(test_file)})

        assert not test_file.exists()
        assert "backup" in result.lower()


# ---------------------------------------------------------------------------
# File Info Tool Tests
# ---------------------------------------------------------------------------


class TestFileInfoTool:
    """Integration tests for file_info tool."""

    def test_get_file_metadata(self, info_tool, tmp_path) -> None:
        """Test getting file metadata."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = info_tool.invoke({"path": str(test_file)})

        # Should return file metadata
        assert "Path:" in result
        assert "Size:" in result
        assert "Modified:" in result

    def test_get_nonexistent_file_info(self, info_tool) -> None:
        """Test getting info for non-existent file."""
        result = info_tool.invoke({"path": "/nonexistent/file.txt"})

        # Should handle gracefully
        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# Edit File Lines Tool Tests
# ---------------------------------------------------------------------------


class TestEditFileLinesTool:
    """Integration tests for edit_lines tool."""

    def test_replace_lines(self, edit_tool, tmp_path) -> None:
        """Test replacing specific line range."""
        test_file = tmp_path / "test.py"
        lines = [f"Line {i}" for i in range(1, 11)]
        test_file.write_text("\n".join(lines))

        result = edit_tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 3,
                "end_line": 5,
                "new_content": "New Line 3\nNew Line 4\nNew Line 5",
            }
        )

        content = test_file.read_text()
        assert "New Line 3" in content
        assert "Line 6" in content  # Line after replaced range should still exist
        assert "Line 2" in content  # Line before replaced range should still exist
        assert "Updated" in result or "updated" in result.lower()

    def test_edit_nonexistent_file(self, edit_tool) -> None:
        """Test editing non-existent file."""
        result = edit_tool.invoke(
            {
                "file_path": "/nonexistent/file.txt",
                "start_line": 1,
                "end_line": 2,
                "new_content": "test",
            }
        )

        assert "Error" in result or "not found" in result.lower()

    def test_invalid_line_range(self, edit_tool, tmp_path) -> None:
        """Test invalid line range."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        result = edit_tool.invoke(
            {"file_path": str(test_file), "start_line": 10, "end_line": 15, "new_content": "test"}
        )

        assert "Error" in result or "Invalid" in result


# ---------------------------------------------------------------------------
# Insert Lines Tool Tests
# ---------------------------------------------------------------------------


class TestInsertLinesTool:
    """Integration tests for insert_lines tool."""

    def test_insert_at_line(self, insert_tool, tmp_path) -> None:
        """Test inserting content at specific line."""
        test_file = tmp_path / "test.py"
        test_file.write_text("Line 1\nLine 2\nLine 3")

        result = insert_tool.invoke(
            {"file_path": str(test_file), "line": 2, "content": "Inserted Line"}
        )

        content = test_file.read_text()
        lines = content.splitlines()
        assert "Inserted Line" in lines[1]  # Should be at line 2
        assert "Line 1" in lines[0]
        assert "Inserted" in result or "inserted" in result.lower()

    def test_insert_at_end(self, insert_tool, tmp_path) -> None:
        """Test inserting at end of file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        _ = insert_tool.invoke({"file_path": str(test_file), "line": 3, "content": "Final Line"})

        content = test_file.read_text()
        assert "Final Line" in content


# ---------------------------------------------------------------------------
# Delete Lines Tool Tests
# ---------------------------------------------------------------------------


class TestDeleteLinesTool:
    """Integration tests for delete_lines tool."""

    def test_delete_line_range(self, delete_lines_tool, tmp_path) -> None:
        """Test deleting specific line range."""
        test_file = tmp_path / "test.py"
        lines = [f"Line {i}" for i in range(1, 11)]
        test_file.write_text("\n".join(lines))

        result = delete_lines_tool.invoke(
            {"file_path": str(test_file), "start_line": 3, "end_line": 5}
        )

        content = test_file.read_text()
        assert "Line 3" not in content
        assert "Line 5" not in content
        assert "Line 6" in content  # Line after deleted range
        assert "Deleted" in result or "deleted" in result.lower()

    def test_delete_invalid_range(self, delete_lines_tool, tmp_path) -> None:
        """Test deleting invalid line range."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2")

        result = delete_lines_tool.invoke(
            {"file_path": str(test_file), "start_line": 10, "end_line": 15}
        )

        assert "Error" in result or "Invalid" in result


# ---------------------------------------------------------------------------
# Apply Diff Tool Tests
# ---------------------------------------------------------------------------


class TestApplyDiffTool:
    """Integration tests for apply_diff tool."""

    def test_apply_simple_diff(self, apply_diff_tool, tmp_path) -> None:
        """Test applying a simple unified diff."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content\n")

        diff = "--- test.txt\n+++ test.txt\n@@ -1 +1 @@\n-Original content\n+Modified content\n"

        result = apply_diff_tool.invoke({"file_path": str(test_file), "diff": diff})

        content = test_file.read_text()
        assert "Modified content" in content
        assert "Applied" in result or "applied" in result.lower()

    def test_apply_invalid_diff(self, apply_diff_tool, tmp_path) -> None:
        """Test applying invalid diff."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = apply_diff_tool.invoke(
            {"file_path": str(test_file), "diff": "invalid diff format"}
        )

        assert "Error" in result or "Failed" in result


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


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
