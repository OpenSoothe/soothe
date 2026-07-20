"""Tests for LangChainAdapter."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from soothe_nano.filesystem import (
    GrepResult,
    LangChainAdapter,
    LocalFilesystem,
    PathNotFoundError,
)
from soothe_nano.filesystem.grep_search import is_grep_available


class TestLangChainAdapter:
    """Test suite for LangChainAdapter."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.fixture
    def underlying_fs(self, temp_dir: Path) -> LocalFilesystem:
        """Create a LocalFilesystem instance."""
        return LocalFilesystem(temp_dir, virtual_mode=True)

    @pytest.fixture
    def adapter(self, underlying_fs: LocalFilesystem) -> LangChainAdapter:
        """Create a LangChainAdapter instance."""
        return LangChainAdapter(underlying_fs)

    def test_init(self, underlying_fs: LocalFilesystem):
        """Test adapter initialization."""
        adapter = LangChainAdapter(underlying_fs)
        assert adapter._underlying is underlying_fs
        assert adapter.workspace == underlying_fs.workspace

    def test_resolve_path(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test path resolution."""
        resolved = adapter.resolve_path("test.txt")
        # Use resolve() to normalize paths (handles /private prefix on macOS)
        assert resolved.resolve() == (temp_dir / "test.txt").resolve()

    def test_exists(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test exists method."""
        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        assert adapter.exists("test.txt") is True
        assert adapter.exists("nonexistent.txt") is False

    def test_is_file(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test is_file method."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        assert adapter.is_file("test.txt") is True
        assert adapter.is_file(".") is False

    def test_is_dir(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test is_dir method."""
        test_dir = temp_dir / "subdir"
        test_dir.mkdir()

        assert adapter.is_dir("subdir") is True
        assert adapter.is_dir("nonexistent") is False

    def test_read(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test read method."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello, World!")

        result = adapter.read("test.txt")
        assert result.content == "Hello, World!"
        assert result.is_binary is False

    def test_read_not_found(self, adapter: LangChainAdapter):
        """Test read raises error for nonexistent file."""
        with pytest.raises(PathNotFoundError):
            adapter.read("nonexistent.txt")

    def test_write(self, adapter: LangChainAdapter):
        """Test write method."""
        result = adapter.write("test.txt", "Hello, World!")
        assert result.path == "test.txt"
        assert result.created is True

        # Verify content
        read_result = adapter.read("test.txt")
        assert read_result.content == "Hello, World!"

    def test_edit(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test edit method."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello, World!")

        result = adapter.edit("test.txt", "World", "Universe")
        assert result.path == "test.txt"
        assert result.lines_changed == 1

        # Verify content
        read_result = adapter.read("test.txt")
        assert read_result.content == "Hello, Universe!"

    def test_delete(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test delete method."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        result = adapter.delete("test.txt")
        assert result.path == "test.txt"
        assert adapter.exists("test.txt") is False

    def test_ls(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test ls method."""
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")

        result = adapter.ls(".")
        assert "file1.txt" in result
        assert "file2.txt" in result

    def test_mkdir(self, adapter: LangChainAdapter):
        """Test mkdir method."""
        result = adapter.mkdir("newdir")
        assert result.path == "newdir"
        assert result.is_dir is True
        assert adapter.is_dir("newdir") is True

    def test_glob(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test glob method."""
        (temp_dir / "test1.py").write_text("content")
        (temp_dir / "test2.py").write_text("content")
        (temp_dir / "test.txt").write_text("content")

        result = adapter.glob("*.py")
        assert len(result.matches) == 2
        assert all(m.endswith(".py") for m in result.matches)

    def test_grep(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test grep method."""
        if not is_grep_available():
            pytest.skip("grep backend is unavailable in this environment")

        (temp_dir / "test1.txt").write_text("hello world")
        (temp_dir / "test2.txt").write_text("hello universe")

        result = adapter.grep("hello")
        if isinstance(result, list):
            assert "test1.txt" in result
            assert "test2.txt" in result
            return
        assert isinstance(result, GrepResult)
        assert any(match.path.endswith("test1.txt") for match in result.matches)
        assert any(match.path.endswith("test2.txt") for match in result.matches)

    def test_info(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test info method."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        result = adapter.info("test.txt")
        assert result.path == "test.txt"
        assert result.is_dir is False
        assert result.size == len("content")

    def test_copy(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test copy method."""
        test_file = temp_dir / "source.txt"
        test_file.write_text("content")

        result = adapter.copy("source.txt", "dest.txt")
        assert result.path == "dest.txt"
        assert adapter.exists("dest.txt") is True

    def test_move(self, adapter: LangChainAdapter, temp_dir: Path):
        """Test move method."""
        test_file = temp_dir / "source.txt"
        test_file.write_text("content")

        result = adapter.move("source.txt", "dest.txt")
        assert result.path == "dest.txt"
        assert adapter.exists("source.txt") is False
        assert adapter.exists("dest.txt") is True

    def test_from_local_filesystem(self, temp_dir: Path):
        """Test factory method from_local_filesystem."""
        adapter = LangChainAdapter.from_local_filesystem(temp_dir)
        assert isinstance(adapter._underlying, LocalFilesystem)
        # Use resolve() to normalize paths (handles /private prefix on macOS)
        assert adapter.workspace.resolve() == temp_dir.resolve()

    def test_async_methods_exist(self, adapter: LangChainAdapter):
        """Test that async methods exist and are callable."""
        import inspect

        async_methods = [
            "aread",
            "awrite",
            "aedit",
            "aedit_lines",
            "ainsert_lines",
            "adelete_lines",
            "aapply_diff",
            "als",
            "amkdir",
            "armdir",
            "adelete",
            "ainfo",
            "acopy",
            "amove",
            "aglob",
            "agrep",
        ]

        for method_name in async_methods:
            assert hasattr(adapter, method_name)
            method = getattr(adapter, method_name)
            assert inspect.iscoroutinefunction(method)
