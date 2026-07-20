"""Tests for soothe_deepagents middleware compatibility with Soothe filesystem backends.

These tests verify that Soothe's UnifiedFilesystem implementations work correctly
with soothe_deepagents.middleware.filesystem.FilesystemMiddleware, which expects:
- ls/als to return LsResult (with .error and .entries attributes)
- edit/aedit to return EditResult (with .error, .path, .occurrences attributes)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe_deepagents.backends.protocol import EditResult, LsResult, WriteResult

from soothe_nano.workspace.workspace_filesystem import (
    NormalizedPathBackend,
    WorkspaceAwareBackend,
)


class TestNormalizedPathBackendReadResult:
    """Test line-based read/aread returning soothe_deepagents ReadResult."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> NormalizedPathBackend:
        """Create backend with a multi-line sample file."""
        lines = [f"line {i}\n" for i in range(1, 31)]
        (tmp_path / "sample.txt").write_text("".join(lines), encoding="utf-8")
        return NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)

    def test_read_returns_read_result(self, backend: NormalizedPathBackend) -> None:
        """read() returns ReadResult with file_data."""
        from soothe_deepagents.backends.protocol import ReadResult

        result = backend.read("/sample.txt", offset=0, limit=5)
        assert isinstance(result, ReadResult)
        assert result.error is None
        assert result.file_data is not None
        assert result.file_data["content"].startswith("line 1")

    def test_read_line_offset_and_limit(self, backend: NormalizedPathBackend) -> None:
        """offset/limit are line-based (not byte-based)."""
        result = backend.read("/sample.txt", offset=25, limit=5)
        assert result.error is None
        assert result.file_data is not None
        content = result.file_data["content"]
        assert "line 26" in content
        assert "line 30" in content
        assert "line 25" not in content

    def test_read_offset_past_eof_returns_error(self, backend: NormalizedPathBackend) -> None:
        """Line offset beyond EOF returns ReadResult.error (no seek crash)."""
        result = backend.read("/sample.txt", offset=100, limit=20)
        assert result.error is not None
        assert "exceeds file length" in result.error
        assert "0-indexed" in result.error

    @pytest.mark.asyncio
    async def test_aread_matches_read(self, backend: NormalizedPathBackend) -> None:
        """aread() uses the same line semantics as read()."""
        sync_result = backend.read("/sample.txt", offset=10, limit=3)
        async_result = await backend.aread("/sample.txt", offset=10, limit=3)
        assert sync_result.error == async_result.error
        assert (sync_result.file_data or {}).get("content") == (async_result.file_data or {}).get(
            "content"
        )


class TestNormalizedPathBackendWriteResult:
    """Test that write/awrite return soothe_deepagents WriteResult per BackendProtocol.

    soothe_deepagents.middleware.filesystem._aprocess_large_message reads
    ``result.error`` to decide whether to evict a large tool result. Returning
    a bare ``str`` (the old behaviour) crashes that codepath with
    ``AttributeError: 'str' object has no attribute 'error'``.
    """

    @pytest.fixture
    def backend(self, tmp_path: Path) -> NormalizedPathBackend:
        return NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)

    def test_write_returns_write_result_on_success(self, backend: NormalizedPathBackend) -> None:
        result = backend.write("/note.txt", "hello world")
        assert isinstance(result, WriteResult)
        assert result.error is None
        assert result.path and result.path.endswith("note.txt")

    @pytest.mark.asyncio
    async def test_awrite_returns_write_result_on_success(
        self, backend: NormalizedPathBackend
    ) -> None:
        result = await backend.awrite("/async-note.txt", "hi")
        assert isinstance(result, WriteResult)
        assert result.error is None
        assert result.path and result.path.endswith("async-note.txt")

    def test_workspace_aware_backend_write_returns_write_result(self, tmp_path: Path) -> None:
        backend = WorkspaceAwareBackend(
            default_root_dir=tmp_path,
            virtual_mode=True,
            max_file_size_mb=10,
        )
        result = backend.write("/file.txt", "payload")
        assert isinstance(result, WriteResult)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_workspace_aware_backend_awrite_returns_write_result(
        self, tmp_path: Path
    ) -> None:
        backend = WorkspaceAwareBackend(
            default_root_dir=tmp_path,
            virtual_mode=True,
            max_file_size_mb=10,
        )
        result = await backend.awrite("/async-file.txt", "payload")
        assert isinstance(result, WriteResult)
        assert result.error is None


class TestNormalizedPathBackendLsResult:
    """Test that NormalizedPathBackend.ls returns LsResult."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory with sample files."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("content2")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.txt").write_text("nested content")
        return tmp_path

    @pytest.fixture
    def backend(self, temp_dir: Path) -> NormalizedPathBackend:
        """Create NormalizedPathBackend instance."""
        return NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)

    def test_ls_returns_ls_result_type(self, backend: NormalizedPathBackend) -> None:
        """Test that ls returns LsResult instance."""
        result = backend.ls(".")
        assert isinstance(result, LsResult), f"Expected LsResult, got {type(result)}"

    def test_ls_result_has_entries(self, backend: NormalizedPathBackend) -> None:
        """Test that LsResult.entries contains file info."""
        result = backend.ls(".")
        assert result.error is None, f"Unexpected error: {result.error}"
        assert result.entries is not None, "entries should not be None"
        assert len(result.entries) >= 3, "Should have at least 3 entries"

    def test_ls_entries_have_required_fields(self, backend: NormalizedPathBackend) -> None:
        """Test that entries have path and is_dir fields."""
        result = backend.ls(".")
        assert result.entries is not None
        for entry in result.entries:
            assert "path" in entry, "Entry must have 'path' field"
            assert "is_dir" in entry, "Entry must have 'is_dir' field"

    def test_ls_identifies_directories(self, backend: NormalizedPathBackend) -> None:
        """Test that ls correctly identifies directories."""
        result = backend.ls(".")
        assert result.entries is not None
        dir_entries = [e for e in result.entries if e.get("is_dir")]
        assert len(dir_entries) >= 1, "Should have at least one directory"
        # Verify is_dir is True for directories
        for entry in dir_entries:
            assert entry.get("is_dir") is True, "Directory entry should have is_dir=True"

    def test_ls_nonexistent_directory_returns_error(self, backend: NormalizedPathBackend) -> None:
        """Test that ls on nonexistent path returns error."""
        result = backend.ls("/nonexistent")
        assert result.error is not None, "Should have error for nonexistent path"
        assert result.entries == [], "Entries should be empty on error"

    @pytest.mark.asyncio
    async def test_als_returns_ls_result_type(self, backend: NormalizedPathBackend) -> None:
        """Test that als returns LsResult instance."""
        result = await backend.als(".")
        assert isinstance(result, LsResult), f"Expected LsResult, got {type(result)}"

    @pytest.mark.asyncio
    async def test_als_result_matches_ls(self, backend: NormalizedPathBackend) -> None:
        """Test that als returns same results as ls."""
        sync_result = backend.ls(".")
        async_result = await backend.als(".")
        assert sync_result.error == async_result.error
        assert len(sync_result.entries or []) == len(async_result.entries or [])


class TestNormalizedPathBackendEditResult:
    """Test that NormalizedPathBackend.edit returns EditResult."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory with sample file."""
        (tmp_path / "test.txt").write_text("Hello World\nLine 2\nLine 3")
        return tmp_path

    @pytest.fixture
    def backend(self, temp_dir: Path) -> NormalizedPathBackend:
        """Create NormalizedPathBackend instance."""
        return NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)

    def test_edit_returns_edit_result_type(
        self, backend: NormalizedPathBackend, temp_dir: Path
    ) -> None:
        """Test that edit returns EditResult instance."""
        result = backend.edit(
            path="test.txt",
            old_string="Hello World",
            new_string="Hello Updated",
        )
        assert isinstance(result, EditResult), f"Expected EditResult, got {type(result)}"

    def test_edit_result_has_path(self, backend: NormalizedPathBackend, temp_dir: Path) -> None:
        """Test that EditResult has path on success."""
        result = backend.edit(
            path="test.txt",
            old_string="Hello World",
            new_string="Hello Updated",
        )
        assert result.error is None, f"Unexpected error: {result.error}"
        assert result.path is not None, "path should be set on success"

    def test_edit_result_has_occurrences(
        self, backend: NormalizedPathBackend, temp_dir: Path
    ) -> None:
        """Test that EditResult has occurrences count."""
        result = backend.edit(
            path="test.txt",
            old_string="Hello World",
            new_string="Hello Updated",
        )
        assert result.error is None
        assert result.occurrences is not None, "occurrences should be set"
        assert result.occurrences >= 1, "Should have at least 1 occurrence"

    def test_edit_nonexistent_file_returns_error(self, backend: NormalizedPathBackend) -> None:
        """Test that edit on nonexistent file returns error."""
        result = backend.edit(
            path="nonexistent.txt",
            old_string="old",
            new_string="new",
        )
        assert result.error is not None, "Should have error for nonexistent file"
        assert result.path is None, "path should be None on error"

    def test_edit_no_match_returns_error(
        self, backend: NormalizedPathBackend, temp_dir: Path
    ) -> None:
        """Test that edit with no matching string returns error."""
        result = backend.edit(
            path="test.txt",
            old_string="NonexistentString",
            new_string="Replacement",
        )
        assert result.error is not None, "Should have error when no match found"

    @pytest.mark.asyncio
    async def test_aedit_returns_edit_result_type(
        self, backend: NormalizedPathBackend, temp_dir: Path
    ) -> None:
        """Test that aedit returns EditResult instance."""
        result = await backend.aedit(
            path="test.txt",
            old_string="Hello World",
            new_string="Hello Async",
        )
        assert isinstance(result, EditResult), f"Expected EditResult, got {type(result)}"

    @pytest.mark.asyncio
    async def test_aedit_result_matches_edit(
        self, backend: NormalizedPathBackend, temp_dir: Path
    ) -> None:
        """Test that aedit returns same structure as edit."""
        # First, reset file content
        (temp_dir / "test.txt").write_text("Original Content\nLine 2")

        sync_result = backend.edit(
            path="test.txt",
            old_string="Original",
            new_string="Synced",
        )

        # Reset again
        (temp_dir / "test.txt").write_text("Original Content\nLine 2")

        async_result = await backend.aedit(
            path="test.txt",
            old_string="Original",
            new_string="Asynced",
        )

        # Both should have same error status
        assert sync_result.error is None
        assert async_result.error is None


class TestWorkspaceAwareBackendCompat:
    """Test that WorkspaceAwareBackend returns soothe_deepagents-compatible results."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory with sample files."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()
        return tmp_path

    @pytest.fixture
    def backend(self, temp_dir: Path) -> WorkspaceAwareBackend:
        """Create WorkspaceAwareBackend instance."""
        return WorkspaceAwareBackend(
            default_root_dir=temp_dir,
            virtual_mode=False,
        )

    def test_ls_returns_ls_result(self, backend: WorkspaceAwareBackend) -> None:
        """Test that ls returns LsResult."""
        result = backend.ls(".")
        assert isinstance(result, LsResult)

    @pytest.mark.asyncio
    async def test_als_returns_ls_result(self, backend: WorkspaceAwareBackend) -> None:
        """Test that als returns LsResult."""
        result = await backend.als(".")
        assert isinstance(result, LsResult)

    def test_edit_returns_edit_result(self, backend: WorkspaceAwareBackend, temp_dir: Path) -> None:
        """Test that edit returns EditResult."""
        result = backend.edit(
            path="file1.txt",
            old_string="content1",
            new_string="updated1",
        )
        assert isinstance(result, EditResult)
        assert result.error is None
        assert result.path is not None

    @pytest.mark.asyncio
    async def test_aedit_returns_edit_result(
        self, backend: WorkspaceAwareBackend, temp_dir: Path
    ) -> None:
        """Test that aedit returns EditResult."""
        result = await backend.aedit(
            path="file2.py",
            old_string="hello",
            new_string="world",
        )
        assert isinstance(result, EditResult)


class TestDeepagentsMiddlewareIntegration:
    """Test that backend results are compatible with soothe_deepagents FilesystemMiddleware expectations.

    These tests verify that NormalizedPathBackend and WorkspaceAwareBackend return
    result types that soothe_deepagents middleware can consume without errors.
    """

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory with sample files."""
        (tmp_path / "readme.md").write_text("# Project\n\nDescription here.")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main():\n    pass")
        return tmp_path

    def test_ls_result_deepagents_compatible(self, temp_dir: Path) -> None:
        """Verify LsResult structure matches soothe_deepagents expectations."""
        backend = NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)
        result = backend.ls(".")

        # Deepagents expects: result.error (str|None) and result.entries (list|None)
        assert hasattr(result, "error"), "LsResult must have 'error' attribute"
        assert hasattr(result, "entries"), "LsResult must have 'entries' attribute"
        assert result.error is None, f"Unexpected error: {result.error}"
        assert isinstance(result.entries, list), "entries must be a list"

        # Each entry should be a dict with 'path' and 'is_dir' keys
        for entry in result.entries:
            assert isinstance(entry, dict), "Each entry must be a dict"
            assert "path" in entry, "Entry must have 'path' key"
            assert "is_dir" in entry, "Entry must have 'is_dir' key"

    def test_edit_result_deepagents_compatible(self, temp_dir: Path) -> None:
        """Verify EditResult structure matches soothe_deepagents expectations."""
        backend = NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)
        result = backend.edit("readme.md", "# Project", "# Updated Project")

        # Deepagents expects: result.error, result.path, result.occurrences
        assert hasattr(result, "error"), "EditResult must have 'error' attribute"
        assert hasattr(result, "path"), "EditResult must have 'path' attribute"
        assert hasattr(result, "occurrences"), "EditResult must have 'occurrences' attribute"
        assert result.error is None, f"Unexpected error: {result.error}"
        assert result.path is not None, "path should be set on success"

    def test_error_result_deepagents_compatible(self, temp_dir: Path) -> None:
        """Verify error EditResult structure matches soothe_deepagents expectations."""
        backend = NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)
        result = backend.edit("nonexistent.txt", "old", "new")

        assert hasattr(result, "error"), "EditResult must have 'error' attribute"
        assert result.error is not None, "Should have error for nonexistent file"
        assert result.path is None, "path should be None on error"

    @pytest.mark.asyncio
    async def test_async_ls_result_deepagents_compatible(self, temp_dir: Path) -> None:
        """Verify async LsResult structure matches soothe_deepagents expectations."""
        backend = NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)
        result = await backend.als(".")

        assert hasattr(result, "error"), "LsResult must have 'error' attribute"
        assert hasattr(result, "entries"), "LsResult must have 'entries' attribute"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_async_edit_result_deepagents_compatible(self, temp_dir: Path) -> None:
        """Verify async EditResult structure matches soothe_deepagents expectations."""
        # Reset file content first
        (temp_dir / "readme.md").write_text("# Async Test Project\n\nDescription.")
        backend = NormalizedPathBackend(root_dir=temp_dir, virtual_mode=False)
        result = await backend.aedit("readme.md", "# Async Test Project", "# Final Project")

        assert hasattr(result, "error"), "EditResult must have 'error' attribute"
        assert hasattr(result, "path"), "EditResult must have 'path' attribute"
        assert result.error is None


class TestBackendTypeCompatibility:
    """Test that Soothe backends work with soothe_deepagents type annotations."""

    def test_ls_result_is_dataclass(self, tmp_path: Path) -> None:
        """Verify LsResult is a dataclass (soothe_deepagents expectation)."""
        from dataclasses import is_dataclass

        backend = NormalizedPathBackend(root_dir=tmp_path)
        result = backend.ls(".")
        assert is_dataclass(result), "LsResult should be a dataclass"

    def test_edit_result_is_dataclass(self, tmp_path: Path) -> None:
        """Verify EditResult is a dataclass (soothe_deepagents expectation)."""
        from dataclasses import is_dataclass

        (tmp_path / "test.txt").write_text("content")
        backend = NormalizedPathBackend(root_dir=tmp_path)
        result = backend.edit("test.txt", "content", "updated")
        assert is_dataclass(result), "EditResult should be a dataclass"

    def test_result_importable_from_deepagents(self) -> None:
        """Verify result types can be imported from soothe_deepagents."""
        from soothe_deepagents.backends.protocol import EditResult, LsResult

        # Should be able to create instances
        ls = LsResult(error=None, entries=[{"path": "test", "is_dir": False}])
        assert ls.entries is not None

        edit = EditResult(error=None, path="test.txt", occurrences=1)
        assert edit.path == "test.txt"


class TestLsResultErrorHandling:
    """Test error handling in ls operations."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> NormalizedPathBackend:
        """Create backend with virtual_mode=True for sandboxed testing."""
        return NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)

    def test_ls_outside_workspace_returns_error(self, backend: NormalizedPathBackend) -> None:
        """Test ls on path outside workspace returns error."""
        # In virtual_mode, trying to list a path that resolves outside workspace should error
        result = backend.ls("/etc")
        # Should either error or return empty entries
        assert result.error is not None or result.entries == []

    def test_ls_invalid_path_handling(self, backend: NormalizedPathBackend) -> None:
        """Test ls handles invalid paths gracefully."""
        # Try to list a path with traversal
        result = backend.ls("../outside")
        # Should return error for path traversal in virtual_mode
        assert result.error is not None


class TestEditResultMultipleEdits:
    """Test edit with multiple edits list."""

    @pytest.fixture
    def temp_file(self, tmp_path: Path) -> Path:
        """Create a file with multiple lines."""
        file = tmp_path / "multi.txt"
        file.write_text("line1\nline2\nline3\n")
        return file

    @pytest.fixture
    def backend(self, tmp_path: Path) -> NormalizedPathBackend:
        """Create backend instance."""
        return NormalizedPathBackend(root_dir=tmp_path, virtual_mode=False)

    def test_edit_with_edits_list(self, backend: NormalizedPathBackend, temp_file: Path) -> None:
        """Test edit with multiple edits in list format."""
        edits = [
            {"old_string": "line1", "new_string": "updated1"},
            {"old_string": "line2", "new_string": "updated2"},
        ]
        result = backend.edit(path="multi.txt", edits=edits)
        assert isinstance(result, EditResult)
        # Should aggregate occurrences from all edits
        assert result.occurrences is not None
        assert result.occurrences >= 2

    @pytest.mark.asyncio
    async def test_aedit_with_edits_list(
        self, backend: NormalizedPathBackend, temp_file: Path
    ) -> None:
        """Test aedit with multiple edits in list format."""
        # Reset file
        temp_file.write_text("lineA\nlineB\nlineC\n")
        edits = [
            {"old_string": "lineA", "new_string": "asyncA"},
        ]
        result = await backend.aedit(path="multi.txt", edits=edits)
        assert isinstance(result, EditResult)
        assert result.error is None
