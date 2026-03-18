"""Tests for File Edit tools functionality."""

import asyncio
import tempfile
from pathlib import Path

from soothe.tools.file_edit import (
    CreateFileTool,
    DeleteFileTool,
    GetFileInfoTool,
    ListFilesTool,
    ReadFileTool,
    SearchInFilesTool,
    create_file_edit_tools,
)


class TestCreateFileTool:
    """Test CreateFileTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = CreateFileTool()

        assert tool.name == "create_file"
        assert "create" in tool.description.lower()
        assert "file" in tool.description.lower()

    def test_create_new_file(self) -> None:
        """Test creating a new file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)

            result = tool._run("test.txt", "Hello, World!")

            assert "Created:" in result
            assert "test.txt" in result

            # Verify file was created
            file_path = Path(temp_dir) / "test.txt"
            assert file_path.exists()
            assert file_path.read_text() == "Hello, World!"

    def test_create_file_in_subdirectory(self) -> None:
        """Test creating file in subdirectory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)

            result = tool._run("subdir/test.txt", "Hello, World!")

            assert "Created:" in result

            # Verify file and directory were created
            file_path = Path(temp_dir) / "subdir" / "test.txt"
            assert file_path.exists()
            assert file_path.read_text() == "Hello, World!"

    def test_create_existing_file_without_overwrite(self) -> None:
        """Test creating file that already exists without overwrite."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)

            # Create file first time
            tool._run("test.txt", "Original content")

            # Try to create again without overwrite
            result = tool._run("test.txt", "New content", overwrite=False)

            assert "Error" in result
            assert "already exists" in result.lower()

    def test_create_existing_file_with_overwrite(self) -> None:
        """Test creating file that already exists with overwrite."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir, backup_enabled=False)

            # Create file first time
            tool._run("test.txt", "Original content")

            # Overwrite
            result = tool._run("test.txt", "New content", overwrite=True)

            assert "Created:" in result

            # Verify content was changed
            file_path = Path(temp_dir) / "test.txt"
            assert file_path.read_text() == "New content"

    def test_create_file_with_backup(self) -> None:
        """Test creating file with backup enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir, backup_enabled=True)

            # Create file first time
            tool._run("test.txt", "Original content")

            # Overwrite
            result = tool._run("test.txt", "New content", overwrite=True)

            assert "backup:" in result.lower()

    def test_path_outside_workdir(self) -> None:
        """Test that paths outside work directory are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)

            result = tool._run("/etc/passwd", "test")

            assert "Error" in result
            assert "outside" in result.lower() or "invalid" in result.lower()

    def test_normalize_stripped_absolute_path_into_workdir(self) -> None:
        """Stripped absolute path should normalize to a workdir-relative path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)

            stripped_abs = str(Path(temp_dir).resolve()).lstrip("/") + "/nested/test.txt"
            result = tool._run(stripped_abs, "Hello")

            assert "Created:" in result
            assert "nested/test.txt" in result
            assert (Path(temp_dir) / "nested" / "test.txt").exists()

    def test_async_create_honors_overwrite_keyword(self) -> None:
        """Async wrapper should pass overwrite as keyword-only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = CreateFileTool(work_dir=temp_dir)
            tool._run("async.txt", "old")

            result = asyncio.run(tool._arun("async.txt", "new", overwrite=True))
            assert "Created:" in result
            assert (Path(temp_dir) / "async.txt").read_text() == "new"


class TestReadFileTool:
    """Test ReadFileTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = ReadFileTool()

        assert tool.name == "read_file"
        assert "read" in tool.description.lower()

    def test_read_existing_file(self) -> None:
        """Test reading an existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = ReadFileTool(work_dir=temp_dir)

            result = tool._run("test.txt")

            assert result == "Hello, World!"

    def test_read_nonexistent_file(self) -> None:
        """Test reading a non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = ReadFileTool(work_dir=temp_dir)

            result = tool._run("nonexistent.txt")

            assert "Error" in result
            assert "not found" in result.lower()

    def test_read_file_with_line_range(self) -> None:
        """Test reading file with line range."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file with multiple lines
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Line 1\nLine 2\nLine 3\nLine 4")

            tool = ReadFileTool(work_dir=temp_dir)

            result = tool._run("test.txt", start_line=2, end_line=3)

            assert "Line 2" in result
            assert "Line 3" in result
            assert "Line 1" not in result
            assert "Line 4" not in result


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
            # Create test file
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
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = DeleteFileTool(work_dir=temp_dir, backup_enabled=True)

            result = tool._run("test.txt")

            assert "backup:" in result.lower()

    def test_async_delete_honors_backup_keyword(self) -> None:
        """Async wrapper should pass backup as keyword-only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")
            tool = DeleteFileTool(work_dir=temp_dir, backup_enabled=False)

            result = asyncio.run(tool._arun("test.txt", backup=False))

            assert "Deleted:" in result
            assert not file_path.exists()


class TestListFilesTool:
    """Test ListFilesTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = ListFilesTool()

        assert tool.name == "list_files"
        assert "list" in tool.description.lower()

    def test_list_files_in_directory(self) -> None:
        """Test listing files in directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "file1.txt").write_text("content")
            (Path(temp_dir) / "file2.py").write_text("content")

            tool = ListFilesTool(work_dir=temp_dir)

            result = tool._run(".")

            assert "file1.txt" in result
            assert "file2.py" in result

    def test_list_files_with_pattern(self) -> None:
        """Test listing files with pattern."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "file1.txt").write_text("content")
            (Path(temp_dir) / "file2.py").write_text("content")

            tool = ListFilesTool(work_dir=temp_dir)

            result = tool._run(".", pattern="*.txt")

            assert "file1.txt" in result
            assert "file2.py" not in result

    def test_async_list_honors_recursive_keyword(self) -> None:
        """Async wrapper should pass recursive as keyword-only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nested = Path(temp_dir) / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "deep.txt").write_text("content")

            tool = ListFilesTool(work_dir=temp_dir)
            result = asyncio.run(tool._arun(".", pattern="*.txt", recursive=True))

            assert "deep.txt" in result


class TestSearchInFilesTool:
    """Test SearchInFilesTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = SearchInFilesTool()

        assert tool.name == "search_in_files"
        assert "search" in tool.description.lower()

    def test_search_in_files(self) -> None:
        """Test searching in files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "file1.txt").write_text("Hello, World!")
            (Path(temp_dir) / "file2.txt").write_text("Goodbye, World!")

            tool = SearchInFilesTool(work_dir=temp_dir)

            result = tool._run("Hello")

            assert "file1.txt" in result
            assert "file2.txt" not in result

    def test_search_with_file_pattern(self) -> None:
        """Test searching with file pattern."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "file1.txt").write_text("Hello, World!")
            (Path(temp_dir) / "file2.py").write_text("Hello, Python!")

            tool = SearchInFilesTool(work_dir=temp_dir)

            result = tool._run("Hello", file_pattern="*.txt")

            assert "file1.txt" in result
            assert "file2.py" not in result

    def test_search_no_matches(self) -> None:
        """Test searching with no matches."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            (Path(temp_dir) / "file.txt").write_text("Hello, World!")

            tool = SearchInFilesTool(work_dir=temp_dir)

            result = tool._run("Nonexistent")

            assert "No matches found" in result


class TestGetFileInfoTool:
    """Test GetFileInfoTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = GetFileInfoTool()

        assert tool.name == "get_file_info"
        assert "info" in tool.description.lower() or "metadata" in tool.description.lower()

    def test_get_file_info(self) -> None:
        """Test getting file info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = GetFileInfoTool(work_dir=temp_dir)

            result = tool._run("test.txt")

            assert "Path:" in result
            assert "Size:" in result
            assert "Modified:" in result

    def test_get_nonexistent_file_info(self) -> None:
        """Test getting info for non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = GetFileInfoTool(work_dir=temp_dir)

            result = tool._run("nonexistent.txt")

            assert "Error" in result
            assert "not found" in result.lower()


class TestCreateFileEditTools:
    """Test factory function."""

    def test_create_file_edit_tools(self) -> None:
        """Test factory function creates all tools."""
        tools = create_file_edit_tools()

        assert len(tools) == 6

        tool_names = {tool.name for tool in tools}
        assert "create_file" in tool_names
        assert "read_file" in tool_names
        assert "delete_file" in tool_names
        assert "list_files" in tool_names
        assert "search_in_files" in tool_names
        assert "get_file_info" in tool_names

    def test_create_file_edit_tools_propagates_work_dir(self) -> None:
        """Factory should propagate work_dir to all file tools."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = create_file_edit_tools(work_dir=temp_dir)
            expected = Path(temp_dir).resolve()
            for tool in tools:
                assert Path(getattr(tool, "work_dir", "")).resolve() == expected
