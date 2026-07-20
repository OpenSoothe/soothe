"""Tests for UnifiedFilesystem interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_nano.filesystem import (
    DirectoryNotEmptyError,
    FilesystemError,
    GrepResult,
    InvalidPathError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
)
from soothe_nano.filesystem.local import LocalFilesystem


class TestUnifiedFilesystem:
    """Test suite for UnifiedFilesystem interface."""

    @pytest.fixture
    def temp_workspace(self, tmp_path: Path) -> LocalFilesystem:
        """Create a temporary workspace filesystem."""
        return LocalFilesystem(workspace=tmp_path, virtual_mode=True)

    @pytest.fixture
    def sample_file(self, temp_workspace: LocalFilesystem) -> str:
        """Create a sample file for testing."""
        content = "Hello, World!\nThis is a test file.\nLine 3."
        temp_workspace.write("test.txt", content)
        return "test.txt"

    @pytest.fixture
    def sample_dir(self, temp_workspace: LocalFilesystem) -> str:
        """Create a sample directory for testing."""
        temp_workspace.mkdir("testdir")
        return "testdir"

    # ===================================================================
    # Path Operations
    # ===================================================================

    def test_resolve_path_relative(self, temp_workspace: LocalFilesystem) -> None:
        """Test resolving relative paths."""
        resolved = temp_workspace.resolve_path("subdir/file.txt")
        assert resolved == temp_workspace.workspace / "subdir" / "file.txt"

    def test_resolve_path_absolute_virtual(self, temp_workspace: LocalFilesystem) -> None:
        """Test resolving absolute paths in virtual mode."""
        resolved = temp_workspace.resolve_path("/subdir/file.txt")
        assert resolved == temp_workspace.workspace / "subdir" / "file.txt"

    def test_resolve_path_traversal_blocked(self, temp_workspace: LocalFilesystem) -> None:
        """Test that path traversal is blocked."""
        with pytest.raises(PathTraversalError):
            temp_workspace.resolve_path("../outside.txt")

        with pytest.raises(PathTraversalError):
            temp_workspace.resolve_path("subdir/../../../etc/passwd")

    def test_resolve_path_null_bytes_blocked(self, temp_workspace: LocalFilesystem) -> None:
        """Test that null bytes are blocked."""
        with pytest.raises(InvalidPathError) as exc_info:
            temp_workspace.resolve_path("file\x00.txt")
        assert exc_info.value.details.get("reason") == "null_bytes"

    def test_resolve_path_home_blocked(self, temp_workspace: LocalFilesystem) -> None:
        """Test that home directory references are blocked."""
        with pytest.raises(InvalidPathError) as exc_info:
            temp_workspace.resolve_path("~/.bashrc")
        assert exc_info.value.details.get("reason") == "home_reference"

    def test_exists(self, temp_workspace: LocalFilesystem, sample_file: str) -> None:
        """Test exists check."""
        assert temp_workspace.exists(sample_file) is True
        assert temp_workspace.exists("nonexistent.txt") is False

    def test_is_file(self, temp_workspace: LocalFilesystem, sample_file: str) -> None:
        """Test is_file check."""
        assert temp_workspace.is_file(sample_file) is True

    def test_is_dir(self, temp_workspace: LocalFilesystem, sample_dir: str) -> None:
        """Test is_dir check."""
        assert temp_workspace.is_dir(sample_dir) is True

    # ===================================================================
    # Read Operations
    # ===================================================================

    def test_read_file(self, temp_workspace: LocalFilesystem, sample_file: str) -> None:
        """Test reading a file."""
        result = temp_workspace.read(sample_file)
        assert "Hello, World!" in result.content
        assert result.is_binary is False
        assert result.encoding == "utf-8"

    def test_read_with_offset(self, temp_workspace: LocalFilesystem) -> None:
        """Test reading with offset."""
        temp_workspace.write("offset.txt", "ABCDEFGHIJ")
        result = temp_workspace.read("offset.txt", offset=5)
        assert result.content == "FGHIJ"

    def test_read_with_limit(self, temp_workspace: LocalFilesystem) -> None:
        """Test reading with limit."""
        temp_workspace.write("limit.txt", "ABCDEFGHIJ")
        result = temp_workspace.read("limit.txt", limit=5)
        assert result.content == "ABCDE"
        assert result.truncated is True

    def test_read_not_found(self, temp_workspace: LocalFilesystem) -> None:
        """Test reading non-existent file."""
        with pytest.raises(PathNotFoundError):
            temp_workspace.read("nonexistent.txt")

    def test_read_not_a_file(self, temp_workspace: LocalFilesystem, sample_dir: str) -> None:
        """Test reading a directory as file."""
        with pytest.raises(NotAFileError):
            temp_workspace.read(sample_dir)

    # ===================================================================
    # Write Operations
    # ===================================================================

    def test_write_file(self, temp_workspace: LocalFilesystem) -> None:
        """Test writing a file."""
        result = temp_workspace.write("new.txt", "New content")
        assert result.created is True
        assert result.bytes_written == len("New content")

        # Verify content
        read_result = temp_workspace.read("new.txt")
        assert read_result.content == "New content"

    def test_write_with_backup(self, temp_workspace: LocalFilesystem) -> None:
        """Test writing with backup creation."""
        temp_workspace.write("backup.txt", "Original")
        result = temp_workspace.write("backup.txt", "Updated", backup=True)

        assert result.backup_path is not None
        assert ".backups/" in result.backup_path

        # Verify backup exists
        backup_full = temp_workspace.workspace / result.backup_path
        assert backup_full.exists()

    def test_write_creates_directories(self, temp_workspace: LocalFilesystem) -> None:
        """Test that write creates parent directories."""
        temp_workspace.write("deep/nested/file.txt", "Content")
        assert temp_workspace.exists("deep/nested/file.txt")

    # ===================================================================
    # Edit Operations
    # ===================================================================

    def test_edit_string(self, temp_workspace: LocalFilesystem) -> None:
        """Test string replacement edit."""
        temp_workspace.write("edit.txt", "Hello World")
        result = temp_workspace.edit("edit.txt", "World", "Universe")

        assert result.lines_changed > 0
        content = temp_workspace.read("edit.txt").content
        assert "Hello Universe" in content

    def test_edit_string_not_found(self, temp_workspace: LocalFilesystem) -> None:
        """Test edit with string not found."""
        temp_workspace.write("edit.txt", "Hello World")
        with pytest.raises(FilesystemError, match="not found"):
            temp_workspace.edit("edit.txt", "Nonexistent", "Replacement")

    def test_edit_lines(self, temp_workspace: LocalFilesystem) -> None:
        """Test line range edit."""
        temp_workspace.write("lines.txt", "Line 1\nLine 2\nLine 3\nLine 4")
        temp_workspace.edit_lines("lines.txt", 2, 3, "New Line 2\nNew Line 3")

        content = temp_workspace.read("lines.txt").content
        assert "Line 1" in content
        assert "New Line 2" in content
        assert "New Line 3" in content
        assert "Line 4" in content
        assert content.splitlines() == ["Line 1", "New Line 2", "New Line 3", "Line 4"]

    def test_insert_lines(self, temp_workspace: LocalFilesystem) -> None:
        """Test inserting lines."""
        temp_workspace.write("insert.txt", "Line 1\nLine 2")
        temp_workspace.insert_lines("insert.txt", 2, "Inserted")

        content = temp_workspace.read("insert.txt").content
        lines = content.split("\n")
        assert lines[0] == "Line 1"
        assert lines[1] == "Inserted"
        assert lines[2] == "Line 2"

    def test_delete_lines(self, temp_workspace: LocalFilesystem) -> None:
        """Test deleting lines."""
        temp_workspace.write("delete.txt", "Line 1\nLine 2\nLine 3\nLine 4")
        temp_workspace.delete_lines("delete.txt", 2, 3)

        content = temp_workspace.read("delete.txt").content
        lines = content.split("\n")
        assert lines[0] == "Line 1"
        assert lines[1] == "Line 4"

    # ===================================================================
    # Directory Operations
    # ===================================================================

    def test_mkdir(self, temp_workspace: LocalFilesystem) -> None:
        """Test creating directory."""
        info = temp_workspace.mkdir("newdir")
        assert info.is_dir is True
        assert temp_workspace.exists("newdir")

    def test_mkdir_recursive(self, temp_workspace: LocalFilesystem) -> None:
        """Test recursive directory creation."""
        info = temp_workspace.mkdir("a/b/c", recursive=True)
        assert info.is_dir is True
        assert temp_workspace.exists("a/b/c")

    def test_ls(self, temp_workspace: LocalFilesystem) -> None:
        """Test listing directory."""
        temp_workspace.write("file1.txt", "1")
        temp_workspace.write("file2.txt", "2")
        temp_workspace.mkdir("subdir")

        entries = temp_workspace.ls(".")
        assert "file1.txt" in entries
        assert "file2.txt" in entries
        assert "subdir" in entries

    def test_ls_with_info(self, temp_workspace: LocalFilesystem) -> None:
        """Test listing with file info."""
        temp_workspace.write("info.txt", "content")
        entries = temp_workspace.ls(".", include_info=True)

        assert len(entries) == 1
        assert entries[0].path == "info.txt"
        assert entries[0].is_dir is False
        assert entries[0].size == len("content")

    def test_rmdir(self, temp_workspace: LocalFilesystem) -> None:
        """Test removing empty directory."""
        temp_workspace.mkdir("emptydir")
        result = temp_workspace.rmdir("emptydir")
        assert result.was_directory is True
        assert not temp_workspace.exists("emptydir")

    def test_rmdir_not_empty(self, temp_workspace: LocalFilesystem) -> None:
        """Test removing non-empty directory without recursive."""
        temp_workspace.mkdir("nonempty")
        temp_workspace.write("nonempty/file.txt", "content")

        with pytest.raises(DirectoryNotEmptyError):
            temp_workspace.rmdir("nonempty", recursive=False)

    def test_rmdir_recursive(self, temp_workspace: LocalFilesystem) -> None:
        """Test recursive directory removal."""
        temp_workspace.mkdir("deep/nested/dir", recursive=True)
        temp_workspace.write("deep/nested/file.txt", "content")

        result = temp_workspace.rmdir("deep", recursive=True)
        assert result.was_directory is True
        assert not temp_workspace.exists("deep")

    # ===================================================================
    # File Operations
    # ===================================================================

    def test_delete_file(self, temp_workspace: LocalFilesystem) -> None:
        """Test deleting a file."""
        temp_workspace.write("delete.txt", "content")
        result = temp_workspace.delete("delete.txt")

        assert result.was_directory is False
        assert not temp_workspace.exists("delete.txt")

    def test_delete_with_backup(self, temp_workspace: LocalFilesystem) -> None:
        """Test deleting with backup."""
        temp_workspace.write("backup.txt", "content")
        result = temp_workspace.delete("backup.txt", backup=True)

        assert result.backup_path is not None
        backup_full = temp_workspace.workspace / result.backup_path
        assert backup_full.exists()

    def test_info(self, temp_workspace: LocalFilesystem, sample_file: str) -> None:
        """Test getting file info."""
        info = temp_workspace.info(sample_file)
        assert info.path == sample_file
        assert info.is_dir is False
        assert info.size > 0
        assert info.modified_at is not None

    def test_copy_file(self, temp_workspace: LocalFilesystem) -> None:
        """Test copying a file."""
        temp_workspace.write("source.txt", "content")
        temp_workspace.copy("source.txt", "dest.txt")

        assert temp_workspace.exists("dest.txt")
        assert temp_workspace.read("dest.txt").content == "content"

    def test_copy_overwrite(self, temp_workspace: LocalFilesystem) -> None:
        """Test copy with overwrite."""
        temp_workspace.write("source.txt", "new")
        temp_workspace.write("dest.txt", "old")

        with pytest.raises(FilesystemError):
            temp_workspace.copy("source.txt", "dest.txt", overwrite=False)

        temp_workspace.copy("source.txt", "dest.txt", overwrite=True)
        assert temp_workspace.read("dest.txt").content == "new"

    def test_move_file(self, temp_workspace: LocalFilesystem) -> None:
        """Test moving a file."""
        temp_workspace.write("old.txt", "content")
        temp_workspace.move("old.txt", "new.txt")

        assert not temp_workspace.exists("old.txt")
        assert temp_workspace.exists("new.txt")
        assert temp_workspace.read("new.txt").content == "content"

    # ===================================================================
    # Search Operations
    # ===================================================================

    def test_glob(self, temp_workspace: LocalFilesystem) -> None:
        """Test glob pattern matching."""
        temp_workspace.write("a.txt", "1")
        temp_workspace.write("b.txt", "2")
        temp_workspace.write("c.py", "3")

        result = temp_workspace.glob("*.txt")
        assert "a.txt" in result.matches
        assert "b.txt" in result.matches
        assert "c.py" not in result.matches

    def test_grep_files_with_matches(self, temp_workspace: LocalFilesystem) -> None:
        """Test grep returning file list."""
        temp_workspace.write("file1.txt", "hello world")
        temp_workspace.write("file2.txt", "goodbye world")
        temp_workspace.write("file3.txt", "no match here")

        result = temp_workspace.grep("world", output_mode="files_with_matches")
        assert isinstance(result, list)
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "file3.txt" not in result

    def test_grep_content(self, temp_workspace: LocalFilesystem) -> None:
        """Test grep returning full results."""
        temp_workspace.write("search.txt", "line 1\nhello world\nline 3")

        result = temp_workspace.grep("hello", output_mode="content")
        assert isinstance(result, GrepResult)
        assert len(result.matches) == 1
        assert result.matches[0].line_content == "hello world"
        assert result.matches[0].line_number == 2

    # ===================================================================
    # Security Tests
    # ===================================================================

    def test_traversal_in_read(self, temp_workspace: LocalFilesystem) -> None:
        """Test traversal detection in read."""
        with pytest.raises(PathTraversalError):
            temp_workspace.read("../etc/passwd")

    def test_traversal_in_write(self, temp_workspace: LocalFilesystem) -> None:
        """Test traversal detection in write."""
        with pytest.raises(PathTraversalError):
            temp_workspace.write("../outside.txt", "content")

    def test_traversal_in_delete(self, temp_workspace: LocalFilesystem) -> None:
        """Test traversal detection in delete."""
        with pytest.raises(PathTraversalError):
            temp_workspace.delete("../important.txt")

    def test_traversal_in_mkdir(self, temp_workspace: LocalFilesystem) -> None:
        """Test traversal detection in mkdir."""
        with pytest.raises(PathTraversalError):
            temp_workspace.mkdir("../outside_dir")

    # ===================================================================
    # Async Tests
    # ===================================================================

    @pytest.mark.asyncio
    async def test_aread(self, temp_workspace: LocalFilesystem) -> None:
        """Test async read."""
        temp_workspace.write("async.txt", "async content")
        result = await temp_workspace.aread("async.txt")
        assert result.content == "async content"

    @pytest.mark.asyncio
    async def test_awrite(self, temp_workspace: LocalFilesystem) -> None:
        """Test async write."""
        result = await temp_workspace.awrite("async.txt", "async content")
        assert result.created is True

    @pytest.mark.asyncio
    async def test_als(self, temp_workspace: LocalFilesystem) -> None:
        """Test async ls."""
        temp_workspace.write("async.txt", "content")
        entries = await temp_workspace.als(".")
        assert "async.txt" in entries


class TestLocalFilesystemNonVirtual:
    """Test LocalFilesystem in non-virtual mode."""

    @pytest.fixture
    def non_virtual_fs(self, tmp_path: Path) -> LocalFilesystem:
        """Create a non-virtual filesystem."""
        return LocalFilesystem(workspace=tmp_path, virtual_mode=False)

    def test_absolute_path_outside_workspace_allowed(self, non_virtual_fs: LocalFilesystem) -> None:
        """Test that absolute paths outside workspace are allowed in non-virtual mode.

        Security layer handles approval/deny logic separately via
        allow_paths_outside_workspace and require_approval_for_outside_paths.
        """
        # /tmp is typically accessible; skip if /etc/passwd not readable
        import os

        if os.path.exists("/etc/hosts") and os.access("/etc/hosts", os.R_OK):
            result = non_virtual_fs.read("/etc/hosts")
            assert result.content  # Should have content
        else:
            # Use a temp file we can guarantee exists
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("test content")
                temp_path = f.name
            try:
                result = non_virtual_fs.read(temp_path)
                assert result.content == "test content"
            finally:
                os.unlink(temp_path)

    def test_absolute_path_inside_workspace_allowed(self, non_virtual_fs: LocalFilesystem) -> None:
        """Test that absolute paths inside workspace are allowed."""
        # Create file using workspace-relative path
        non_virtual_fs.write("test.txt", "content")

        # Should be able to read with absolute path
        abs_path = str(non_virtual_fs.workspace / "test.txt")
        result = non_virtual_fs.read(abs_path)
        assert result.content == "content"
