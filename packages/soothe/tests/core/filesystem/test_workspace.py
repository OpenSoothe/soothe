"""Tests for WorkspaceFilesystem."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from soothe.core.filesystem import (
    LocalFilesystem,
    WorkspaceFilesystem,
    FileInfo,
    ReadResult,
    WriteResult,
    GrepResult,
)


class TestWorkspaceFilesystem:
    """Test suite for WorkspaceFilesystem."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.fixture
    def workspace_fs(self, temp_dir: Path) -> WorkspaceFilesystem:
        """Create a WorkspaceFilesystem instance."""
        return WorkspaceFilesystem(temp_dir, virtual_mode=True)

    def test_init(self, temp_dir: Path):
        """Test initialization."""
        fs = WorkspaceFilesystem(temp_dir, virtual_mode=True)
        
        assert fs.workspace.resolve() == temp_dir.resolve()
        assert fs.virtual_mode is True

    def test_get_local_filesystem(self, workspace_fs: WorkspaceFilesystem):
        """Test get_local_filesystem method."""
        local_fs = workspace_fs.get_local_filesystem()
        assert isinstance(local_fs, LocalFilesystem)

    def test_resolve_path(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test path resolution."""
        resolved = workspace_fs.resolve_path("test.txt")
        assert resolved.resolve() == (temp_dir / "test.txt").resolve()

    def test_exists(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test exists method."""
        # Create a test file
        (temp_dir / "exists_test.txt").write_text("test")
        
        assert workspace_fs.exists("exists_test.txt") is True
        assert workspace_fs.exists("nonexistent.txt") is False

    def test_read_write(self, workspace_fs: WorkspaceFilesystem):
        """Test read and write operations."""
        # Write content
        write_result = workspace_fs.write("test.txt", "Hello, World!")
        assert isinstance(write_result, WriteResult)
        assert write_result.path == "test.txt"
        
        # Read content
        read_result = workspace_fs.read("test.txt")
        assert isinstance(read_result, ReadResult)
        assert read_result.content == "Hello, World!"

    def test_ls(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test directory listing."""
        # Create test files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        
        result = workspace_fs.ls(".")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_mkdir(self, workspace_fs: WorkspaceFilesystem):
        """Test directory creation."""
        info = workspace_fs.mkdir("new_dir")
        assert isinstance(info, FileInfo)
        assert info.is_dir is True
        assert info.path.endswith("new_dir")

    def test_delete(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test file deletion."""
        # Create and then delete a file
        (temp_dir / "delete_me.txt").write_text("delete me")
        
        result = workspace_fs.delete("delete_me.txt")
        assert result.path == "delete_me.txt"
        assert not (temp_dir / "delete_me.txt").exists()

    def test_glob(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test glob pattern matching."""
        # Create test files
        (temp_dir / "test1.py").write_text("python")
        (temp_dir / "test2.py").write_text("python")
        (temp_dir / "test.txt").write_text("text")
        
        result = workspace_fs.glob("**/*.py")
        assert len(result.matches) == 2

    def test_grep(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test grep search."""
        # Create test file with searchable content
        (temp_dir / "search.txt").write_text("Hello World\nSearch for this\nAnother line")
        
        result = workspace_fs.grep("Search", path=".", output_mode="content")
        assert isinstance(result, GrepResult)
        assert len(result.matches) == 1

    def test_copy(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test file copy."""
        (temp_dir / "source.txt").write_text("copy me")
        
        result = workspace_fs.copy("source.txt", "dest.txt")
        assert result.path.endswith("dest.txt")
        assert (temp_dir / "dest.txt").exists()

    def test_move(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test file move."""
        (temp_dir / "old.txt").write_text("move me")
        
        result = workspace_fs.move("old.txt", "new.txt")
        assert result.path.endswith("new.txt")
        assert (temp_dir / "new.txt").exists()
        assert not (temp_dir / "old.txt").exists()

    def test_info(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test file info retrieval."""
        (temp_dir / "info_test.txt").write_text("test content")
        
        info = workspace_fs.info("info_test.txt")
        assert isinstance(info, FileInfo)
        assert info.path.endswith("info_test.txt")
        assert info.is_dir is False
        assert info.size == len("test content")

    def test_is_file_is_dir(self, workspace_fs: WorkspaceFilesystem, temp_dir: Path):
        """Test is_file and is_dir methods."""
        (temp_dir / "file.txt").write_text("content")
        (temp_dir / "subdir").mkdir()
        
        assert workspace_fs.is_file("file.txt") is True
        assert workspace_fs.is_file("subdir") is False
        assert workspace_fs.is_dir("subdir") is True
        assert workspace_fs.is_dir("file.txt") is False
