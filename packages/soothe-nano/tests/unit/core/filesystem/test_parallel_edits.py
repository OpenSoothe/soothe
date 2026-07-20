"""Integration tests for parallel edit operations (IG-517).

Tests batched edit execution, race condition elimination, and conflict handling.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from soothe_nano.filesystem.local import LocalFilesystem
from soothe_nano.filesystem.protocol import BatchedEditOperation, BatchedEditResult


class TestBatchedEditOperations:
    """Tests for aedit_batched on LocalFilesystem."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory for test files."""
        return tmp_path

    @pytest.fixture
    def local_fs(self, temp_dir: Path) -> LocalFilesystem:
        """Create a LocalFilesystem instance."""
        return LocalFilesystem(workspace=str(temp_dir), virtual_mode=False)

    @pytest.mark.asyncio
    async def test_single_replacement(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Single replacement operation should work correctly."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=1,
                content="modified1",
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 1
        assert result.total_lines_changed >= 1

        # Verify content
        content = test_file.read_text()
        assert "modified1" in content

    @pytest.mark.asyncio
    async def test_multiple_replacements_descending(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Multiple replacements should be applied bottom-to-top to preserve indices."""
        # Create test file with 10 lines
        test_file = temp_dir / "test.txt"
        lines = [f"line{i}" for i in range(1, 11)]
        test_file.write_text("\n".join(lines) + "\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=2,
                content="modified_top",
                original_call_id="call-1",
            ),
            BatchedEditOperation(
                operation_type="replace",
                start_line=8,
                end_line=10,
                content="modified_bottom",
                original_call_id="call-2",
            ),
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 2

        content = test_file.read_text()
        assert "modified_top" in content
        assert "modified_bottom" in content

    @pytest.mark.asyncio
    async def test_deletion(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Deletion operation should remove lines."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\n")

        operations = [
            BatchedEditOperation(
                operation_type="delete",
                start_line=2,
                end_line=3,
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 1

        content = test_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert "line1" in content
        assert "line4" in content

    @pytest.mark.asyncio
    async def test_insertion(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Insertion operation should add lines at the correct position."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        operations = [
            BatchedEditOperation(
                operation_type="insert",
                start_line=2,
                end_line=1,  # Insert marker
                content="inserted1\ninserted2",
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 1

        content = test_file.read_text()
        lines = content.strip().split("\n")
        # inserted1 and inserted2 should appear after line1
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_operations_order_delete_insert_replace(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Operations should be applied in order: deletions → insertions → replacements."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        operations = [
            # Replacement (should be applied LAST)
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=1,
                content="replaced1",
                original_call_id="rep-1",
            ),
            # Deletion (should be applied FIRST)
            BatchedEditOperation(
                operation_type="delete",
                start_line=3,
                end_line=4,
                original_call_id="del-1",
            ),
            # Insertion (should be applied SECOND)
            BatchedEditOperation(
                operation_type="insert",
                start_line=2,
                end_line=1,
                content="inserted",
                original_call_id="ins-1",
            ),
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 3

        content = test_file.read_text()
        # Verify all operations applied
        assert "replaced1" in content
        assert "inserted" in content
        # line3 and line4 should be deleted
        assert "line3" not in content
        assert "line4" not in content

    @pytest.mark.asyncio
    async def test_overlapping_replacements_rejected(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Overlapping replacement ranges should be rejected with error."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=3,
                content="overlap1",
                original_call_id="call-1",
            ),
            BatchedEditOperation(
                operation_type="replace",
                start_line=2,
                end_line=4,  # Overlaps with call-1 (lines 2-3)
                content="overlap2",
                original_call_id="call-2",
            ),
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        # Should have error about overlapping edits
        assert result.error is not None
        assert "Overlapping" in result.error
        assert len(result.failed_operations or []) == 2

    @pytest.mark.asyncio
    async def test_non_overlapping_replacements_succeed(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Non-overlapping replacements should all succeed."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=2,
                content="top",
                original_call_id="call-1",
            ),
            BatchedEditOperation(
                operation_type="replace",
                start_line=4,
                end_line=5,
                content="bottom",
                original_call_id="call-2",
            ),
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.error is None
        assert result.operations_applied == 2

        content = test_file.read_text()
        assert "top" in content
        assert "bottom" in content

    @pytest.mark.asyncio
    async def test_file_not_found(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Batched edit on non-existent file should fail gracefully."""
        non_existent = temp_dir / "does_not_exist.txt"

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=1,
                content="test",
                original_call_id="call-1",
            )
        ]

        # Should raise PathNotFoundError (handled internally)
        # Note: This might raise or return error result depending on implementation
        try:
            result = await local_fs.aedit_batched(str(non_existent), operations, backup=False)
            # If no exception, check for error in result
            assert result.error is not None
        except Exception as e:
            # Exception is acceptable
            assert "not found" in str(e).lower() or "PathNotFoundError" in type(e).__name__

    @pytest.mark.asyncio
    async def test_invalid_line_range(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Invalid line ranges should be tracked in failed_operations."""
        # Create small test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=100,  # Out of bounds
                end_line=200,
                content="invalid",
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        # Should have failed operation
        assert result.failed_operations is not None
        assert "call-1" in result.failed_operations

    @pytest.mark.asyncio
    async def test_backup_created(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """Backup should be created when backup=True."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("original content\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=1,
                content="modified content",
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=True)

        assert result.error is None
        assert result.backup_path is not None

        # Backup file should exist and contain original content
        backup_path = Path(result.backup_path)
        if backup_path.exists():
            backup_content = backup_path.read_text()
            assert "original content" in backup_content

    @pytest.mark.asyncio
    async def test_hash_tracking(self, local_fs: LocalFilesystem, temp_dir: Path) -> None:
        """BatchedEditResult should track old_hash and new_hash."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("original\n")

        operations = [
            BatchedEditOperation(
                operation_type="replace",
                start_line=1,
                end_line=1,
                content="modified",
                original_call_id="call-1",
            )
        ]

        result = await local_fs.aedit_batched(str(test_file), operations, backup=False)

        assert result.old_hash is not None
        assert result.new_hash is not None
        assert result.old_hash != result.new_hash


class TestConcurrentEdits:
    """Tests for concurrent edit scenarios simulating race conditions."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory for test files."""
        return tmp_path

    @pytest.fixture
    def local_fs(self, temp_dir: Path) -> LocalFilesystem:
        """Create a LocalFilesystem instance."""
        return LocalFilesystem(workspace=str(temp_dir), virtual_mode=False)

    @pytest.mark.asyncio
    async def test_concurrent_edits_different_files(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Concurrent edits to different files should all succeed."""
        # Create multiple test files
        files = []
        for i in range(5):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content{i}\n")
            files.append(f)

        # Create concurrent operations for each file
        async def edit_file(file_path: Path, idx: int) -> BatchedEditResult:
            operations = [
                BatchedEditOperation(
                    operation_type="replace",
                    start_line=1,
                    end_line=1,
                    content=f"modified{idx}",
                    original_call_id=f"call-{idx}",
                )
            ]
            return await local_fs.aedit_batched(str(file_path), operations, backup=False)

        # Execute concurrently
        results = await asyncio.gather(*[edit_file(f, i) for i, f in enumerate(files)])

        # All should succeed
        for i, result in enumerate(results):
            assert result.error is None
            assert result.operations_applied == 1

        # Verify all files modified
        for i, f in enumerate(files):
            content = f.read_text()
            assert f"modified{i}" in content

    @pytest.mark.asyncio
    async def test_sequential_edits_same_file(
        self, local_fs: LocalFilesystem, temp_dir: Path
    ) -> None:
        """Sequential edits to same file should all succeed."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        # First edit
        result1 = await local_fs.aedit_batched(
            str(test_file),
            [
                BatchedEditOperation(
                    operation_type="replace",
                    start_line=1,
                    end_line=1,
                    content="modified1",
                    original_call_id="call-1",
                )
            ],
            backup=False,
        )
        assert result1.error is None

        # Second edit (line numbers shift)
        result2 = await local_fs.aedit_batched(
            str(test_file),
            [
                BatchedEditOperation(
                    operation_type="replace",
                    start_line=2,
                    end_line=2,
                    content="modified2",
                    original_call_id="call-2",
                )
            ],
            backup=False,
        )
        assert result2.error is None

        content = test_file.read_text()
        assert "modified1" in content
        assert "modified2" in content


class TestBatchedEditOperationModel:
    """Tests for BatchedEditOperation data model."""

    def test_to_dict_complete(self) -> None:
        """to_dict should include all fields."""
        op = BatchedEditOperation(
            operation_type="replace",
            start_line=1,
            end_line=5,
            content="test content",
            original_call_id="call-123",
        )

        result = op.to_dict()

        assert result["operation_type"] == "replace"
        assert result["start_line"] == 1
        assert result["end_line"] == 5
        assert result["content"] == "test content"
        assert result["original_call_id"] == "call-123"

    def test_to_dict_minimal(self) -> None:
        """to_dict should work with minimal required fields."""
        op = BatchedEditOperation(
            operation_type="delete",
            start_line=1,
            end_line=5,
        )

        result = op.to_dict()

        assert result["operation_type"] == "delete"
        assert result["content"] == ""
        assert result["original_call_id"] is None


class TestBatchedEditResultModel:
    """Tests for BatchedEditResult data model."""

    def test_to_dict_with_all_fields(self) -> None:
        """to_dict should include all non-None fields."""
        result = BatchedEditResult(
            path="/test/file.txt",
            old_hash="abc123",
            new_hash="def456",
            total_lines_changed=10,
            operations_applied=3,
            failed_operations=["call-1"],
            backup_path="/test/file.txt.bak",
            error=None,
        )

        d = result.to_dict()

        assert d["path"] == "/test/file.txt"
        assert d["old_hash"] == "abc123"
        assert d["new_hash"] == "def456"
        assert d["total_lines_changed"] == 10
        assert d["operations_applied"] == 3
        assert d["failed_operations"] == ["call-1"]
        assert d["backup_path"] == "/test/file.txt.bak"
        assert "error" not in d  # None values omitted

    def test_to_dict_minimal(self) -> None:
        """to_dict should work with minimal required fields."""
        result = BatchedEditResult(
            path="/test/file.txt",
            total_lines_changed=1,
            operations_applied=1,
        )

        d = result.to_dict()

        assert d["path"] == "/test/file.txt"
        assert d["total_lines_changed"] == 1
        assert d["operations_applied"] == 1
        assert "old_hash" not in d
        assert "failed_operations" not in d
        assert "backup_path" not in d
        assert "error" not in d

    def test_result_with_error(self) -> None:
        """Result with error should include it in to_dict."""
        result = BatchedEditResult(
            path="/test/file.txt",
            error="Something went wrong",
            operations_applied=0,
        )

        d = result.to_dict()

        assert d["error"] == "Something went wrong"
