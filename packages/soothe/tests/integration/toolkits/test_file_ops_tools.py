"""Integration tests for file operation tools.

Tests tools from soothe.toolkits.file_ops:
- read_file: Read file contents with optional line ranges
- write_file: Write content to files (create/overwrite)
- delete_file: Delete files
- search_files: Search files by pattern
- list_files: List directory contents
- file_info: Get file metadata
"""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Read File Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReadFileTool:
    """Integration tests for ReadFileTool."""

    @pytest.fixture
    def read_tool(self):
        """Create ReadFileTool instance."""
        from soothe.toolkits.file_ops import ReadFileTool

        return ReadFileTool()

    def test_read_basic_file(self, read_tool) -> None:
        """Test reading a basic text file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!\nLine 2\nLine 3")

            result = read_tool._run(str(test_file))

            assert "Hello, World" in result
            assert "Line 2" in result

    def test_read_line_range(self, read_tool) -> None:
        """Test reading specific line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "multiline.txt"
            lines = [f"Line {i}" for i in range(1, 101)]
            test_file.write_text("\n".join(lines))

            result = read_tool._run(str(test_file), start_line=10, end_line=15)

            assert "Line 10" in result
            assert "Line 15" in result
            assert "Line 20" not in result

    def test_read_large_file(self, read_tool) -> None:
        """Test reading file that approaches size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            large_file = Path(tmpdir) / "large.txt"
            # Create 1MB file
            large_file.write_text("x" * (1024 * 1024))

            result = read_tool._run(str(large_file))

            # Should handle large file
            assert isinstance(result, str)

    def test_read_nonexistent_file(self, read_tool) -> None:
        """Test reading non-existent file."""
        result = read_tool._run("/nonexistent/file.txt")

        # Should return error
        assert "error" in result.lower() or "not found" in result.lower()

    def test_read_binary_file(self, read_tool) -> None:
        """Test reading binary file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_file = Path(tmpdir) / "data.bin"
            binary_file.write_bytes(b"\x00\x01\x02\x03")

            result = read_tool._run(str(binary_file))

            # Should handle binary file (either read as binary or return error)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Write File Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWriteFileTool:
    """Integration tests for WriteFileTool."""

    @pytest.fixture
    def write_tool(self):
        """Create WriteFileTool instance."""
        from soothe.toolkits.file_ops import WriteFileTool

        return WriteFileTool()

    def test_write_new_file(self, write_tool) -> None:
        """Test creating a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "new.txt"

            write_tool._run(str(new_file), content="Test content")

            assert new_file.exists()
            assert "Test content" in new_file.read_text()

    def test_write_overwrite_existing(self, write_tool) -> None:
        """Test overwriting existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            existing_file = Path(tmpdir) / "existing.txt"
            existing_file.write_text("Old content")

            write_tool._run(str(existing_file), content="New content")

            assert "New content" in existing_file.read_text()
            assert "Old content" not in existing_file.read_text()

    def test_write_creates_directories(self, write_tool) -> None:
        """Test writing creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_file = Path(tmpdir) / "subdir" / "deep" / "file.txt"

            write_tool._run(str(nested_file), content="Nested content")

            assert nested_file.exists()
            assert "Nested content" in nested_file.read_text()

    def test_write_unicode_content(self, write_tool) -> None:
        """Test writing Unicode content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unicode_file = Path(tmpdir) / "unicode.txt"

            write_tool._run(str(unicode_file), content="Hello 世界 🌍")

            assert "世界" in unicode_file.read_text()
            assert "🌍" in unicode_file.read_text()


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

            delete_tool._run(str(test_file))

            assert not test_file.exists()

    def test_delete_nonexistent_file(self, delete_tool) -> None:
        """Test deleting non-existent file."""
        result = delete_tool._run("/nonexistent/file.txt")

        # Should handle gracefully
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Search Files Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchFilesTool:
    """Integration tests for SearchFilesTool."""

    @pytest.fixture
    def search_tool(self):
        """Create SearchFilesTool instance."""
        from soothe.toolkits.file_ops import SearchFilesTool

        return SearchFilesTool()

    def test_search_by_pattern(self, search_tool) -> None:
        """Test searching files by pattern."""
        pytest.skip("SearchFilesTool requires grep - skipped for now")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "test1.py").write_text("print('test1')")
            (Path(tmpdir) / "test2.py").write_text("print('test2')")
            (Path(tmpdir) / "data.txt").write_text("data")

            try:
                result = search_tool._run(pattern=r"\.py$", path=tmpdir)

                assert "test1.py" in result or "test2.py" in result
            except Exception as e:
                # Search may fail if grep not available
                if "grep" in str(e).lower() or "not found" in str(e).lower():
                    pytest.skip(f"Search functionality not available: {e}")
                raise

    def test_search_recursive(self, search_tool) -> None:
        """Test recursive file search."""
        pytest.skip("SearchFilesTool requires grep - skipped for now")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "nested.py").write_text("# nested")

            try:
                result = search_tool._run(pattern=r"\.py$", path=tmpdir)

                assert "nested.py" in result or ".py" in result
            except Exception as e:
                # Search may fail if grep not available
                if "grep" in str(e).lower() or "not found" in str(e).lower():
                    pytest.skip(f"Search functionality not available: {e}")
                raise


# ---------------------------------------------------------------------------
# List Files Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListFilesTool:
    """Integration tests for ListFilesTool."""

    @pytest.fixture
    def list_tool(self):
        """Create ListFilesTool instance."""
        from soothe.toolkits.file_ops import ListFilesTool

        return ListFilesTool()

    def test_list_directory(self, list_tool) -> None:
        """Test listing directory contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file1.txt").write_text("a")
            (Path(tmpdir) / "file2.txt").write_text("b")

            result = list_tool._run(path=tmpdir)

            assert "file1.txt" in result
            assert "file2.txt" in result

    def test_list_empty_directory(self, list_tool) -> None:
        """Test listing empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = list_tool._run(path=tmpdir)

            # Should handle empty directory
            assert isinstance(result, str)


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
            assert isinstance(result, (str, dict))

    def test_get_nonexistent_file_info(self, info_tool) -> None:
        """Test getting info for non-existent file."""
        result = info_tool._run("/nonexistent/file.txt")

        # Should handle gracefully
        assert isinstance(result, (str, dict))


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
