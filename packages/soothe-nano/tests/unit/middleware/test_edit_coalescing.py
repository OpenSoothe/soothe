"""Tests for EditCoalescingMiddleware (IG-517).

Tests detection window, grouping, merging, conflict detection, and batch execution.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe_nano.filesystem.protocol import BatchedEditOperation
from soothe_nano.middleware.edit_coalescing import (
    DEFAULT_DETECTION_WINDOW_MS,
    EDIT_TOOL_NAMES,
    EditBatch,
    EditCoalescingConfig,
    EditCoalescingMiddleware,
    EditConflictError,
    PendingEdit,
    _resolve_edit_future,
)


def _make_request(
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str = "test-id",
) -> MagicMock:
    """Create a mock ToolCallRequest."""
    request = MagicMock()
    request.tool_call = {
        "name": tool_name,
        "id": tool_call_id,
        "args": tool_args,
    }
    request.metadata = {}
    return request


def _make_async_handler(result: str = "success") -> Callable[[Any], Awaitable[ToolMessage]]:
    """Create an async handler that returns a ToolMessage."""

    async def handler(request: Any) -> ToolMessage:
        await asyncio.sleep(0.001)
        return ToolMessage(
            content=result,
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler


class TestPendingEdit:
    """Tests for PendingEdit dataclass."""

    @pytest.mark.asyncio
    async def test_pending_edit_creation(self) -> None:
        """PendingEdit should store all required fields."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ToolMessage] = loop.create_future()
        request = _make_request("edit_lines", {"file_path": "/test.txt"})
        handler = _make_async_handler()

        pending = PendingEdit(
            tool_call_id="call-123",
            tool_name="edit_lines",
            file_path="/test.txt",
            args={"start": 1, "end": 5, "new_content": "test"},
            result_future=future,
            handler=handler,
            request=request,
        )

        assert pending.tool_call_id == "call-123"
        assert pending.tool_name == "edit_lines"
        assert pending.file_path == "/test.txt"
        assert pending.args["start"] == 1
        assert pending.args["end"] == 5


class TestEditBatch:
    """Tests for EditBatch dataclass and to_operations transformation."""

    def test_empty_batch(self) -> None:
        """Empty batch should produce empty operations list."""
        batch = EditBatch(file_path="/test.txt", edits=[])
        operations = batch.to_operations()
        assert operations == []

    @pytest.mark.asyncio
    async def test_single_deletion(self) -> None:
        """Single deletion should produce one delete operation."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ToolMessage] = loop.create_future()
        pending = PendingEdit(
            tool_call_id="del-1",
            tool_name="delete_lines",
            file_path="/test.txt",
            args={"start": 10, "end": 20},
            result_future=future,
            handler=_make_async_handler(),
            request=_make_request("delete_lines", {"start": 10, "end": 20}),
        )

        batch = EditBatch(file_path="/test.txt", edits=[pending])
        operations = batch.to_operations()

        assert len(operations) == 1
        assert operations[0].operation_type == "delete"
        assert operations[0].start_line == 10
        assert operations[0].end_line == 20
        assert operations[0].original_call_id == "del-1"

    @pytest.mark.asyncio
    async def test_single_insertion(self) -> None:
        """Single insertion should produce one insert operation."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ToolMessage] = loop.create_future()
        pending = PendingEdit(
            tool_call_id="ins-1",
            tool_name="insert_lines",
            file_path="/test.txt",
            args={"line": 5, "content": "new line"},
            result_future=future,
            handler=_make_async_handler(),
            request=_make_request("insert_lines", {"line": 5, "content": "new line"}),
        )

        batch = EditBatch(file_path="/test.txt", edits=[pending])
        operations = batch.to_operations()

        assert len(operations) == 1
        assert operations[0].operation_type == "insert"
        assert operations[0].start_line == 5
        assert operations[0].end_line == 4  # Insert mode marker
        assert operations[0].content == "new line"

    @pytest.mark.asyncio
    async def test_single_replacement(self) -> None:
        """Single replacement should produce one replace operation."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ToolMessage] = loop.create_future()
        pending = PendingEdit(
            tool_call_id="rep-1",
            tool_name="edit_lines",
            file_path="/test.txt",
            args={"start": 1, "end": 3, "new_content": "replaced"},
            result_future=future,
            handler=_make_async_handler(),
            request=_make_request("edit_lines", {"start": 1, "end": 3, "new_content": "replaced"}),
        )

        batch = EditBatch(file_path="/test.txt", edits=[pending])
        operations = batch.to_operations()

        assert len(operations) == 1
        assert operations[0].operation_type == "replace"
        assert operations[0].start_line == 1
        assert operations[0].end_line == 3
        assert operations[0].content == "replaced"

    @pytest.mark.asyncio
    async def test_operations_order_deletions_first(self) -> None:
        """Operations should be ordered: deletions, insertions, then replacements."""
        loop = asyncio.get_running_loop()

        # Create one of each type
        del_future: asyncio.Future[ToolMessage] = loop.create_future()
        deletion = PendingEdit(
            tool_call_id="del-1",
            tool_name="delete_lines",
            file_path="/test.txt",
            args={"start": 5, "end": 10},
            result_future=del_future,
            handler=_make_async_handler(),
            request=_make_request("delete_lines", {"start": 5, "end": 10}),
        )

        ins_future: asyncio.Future[ToolMessage] = loop.create_future()
        insertion = PendingEdit(
            tool_call_id="ins-1",
            tool_name="insert_lines",
            file_path="/test.txt",
            args={"line": 2, "content": "inserted"},
            result_future=ins_future,
            handler=_make_async_handler(),
            request=_make_request("insert_lines", {"line": 2, "content": "inserted"}),
        )

        rep_future: asyncio.Future[ToolMessage] = loop.create_future()
        replacement = PendingEdit(
            tool_call_id="rep-1",
            tool_name="edit_lines",
            file_path="/test.txt",
            args={"start": 1, "end": 1, "new_content": "replaced"},
            result_future=rep_future,
            handler=_make_async_handler(),
            request=_make_request("edit_lines", {"start": 1, "end": 1, "new_content": "replaced"}),
        )

        # Add in random order
        batch = EditBatch(file_path="/test.txt", edits=[replacement, deletion, insertion])
        operations = batch.to_operations()

        # Should be reordered: delete, insert, replace
        assert len(operations) == 3
        assert operations[0].operation_type == "delete"
        assert operations[1].operation_type == "insert"
        assert operations[2].operation_type == "replace"

    @pytest.mark.asyncio
    async def test_replacements_sorted_descending(self) -> None:
        """Replacements should be sorted by line number descending."""
        loop = asyncio.get_running_loop()

        # Create multiple replacements
        futures = [loop.create_future() for _ in range(3)]
        replacements = [
            PendingEdit(
                tool_call_id=f"rep-{i}",
                tool_name="edit_lines",
                file_path="/test.txt",
                args={"start": start, "end": start + 2, "new_content": f"content-{i}"},
                result_future=futures[i],
                handler=_make_async_handler(),
                request=_make_request(
                    "edit_lines",
                    {"start": start, "end": start + 2, "new_content": f"content-{i}"},
                ),
            )
            for i, start in enumerate([5, 1, 10])  # Out of order
        ]

        batch = EditBatch(file_path="/test.txt", edits=replacements)
        operations = batch.to_operations()

        # Should be sorted: 10, 5, 1 (descending)
        assert len(operations) == 3
        assert operations[0].start_line == 10
        assert operations[1].start_line == 5
        assert operations[2].start_line == 1

    @pytest.mark.asyncio
    async def test_multiple_deletions(self) -> None:
        """Multiple deletions should all be included."""
        loop = asyncio.get_running_loop()
        futures = [loop.create_future() for _ in range(2)]
        deletions = [
            PendingEdit(
                tool_call_id=f"del-{i}",
                tool_name="delete_lines",
                file_path="/test.txt",
                args={"start": s, "end": e},
                result_future=futures[i],
                handler=_make_async_handler(),
                request=_make_request("delete_lines", {"start": s, "end": e}),
            )
            for i, (s, e) in enumerate([(1, 5), (10, 15)])
        ]

        batch = EditBatch(file_path="/test.txt", edits=deletions)
        operations = batch.to_operations()

        assert len(operations) == 2
        assert all(op.operation_type == "delete" for op in operations)

    @pytest.mark.asyncio
    async def test_missing_args_use_defaults(self) -> None:
        """Missing args should use default values."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ToolMessage] = loop.create_future()
        pending = PendingEdit(
            tool_call_id="del-defaults",
            tool_name="delete_lines",
            file_path="/test.txt",
            args={},  # Missing start/end
            result_future=future,
            handler=_make_async_handler(),
            request=_make_request("delete_lines", {}),
        )

        batch = EditBatch(file_path="/test.txt", edits=[pending])
        operations = batch.to_operations()

        assert len(operations) == 1
        assert operations[0].start_line == 1  # Default
        assert operations[0].end_line == 1  # Default


class TestEditConflictError:
    """Tests for EditConflictError exception."""

    def test_conflict_error_creation(self) -> None:
        """EditConflictError should store conflict details."""
        error = EditConflictError(
            file_path="/test.txt",
            conflicting_ranges=[(1, 5), (3, 10)],
            edit_ids=["edit-1", "edit-2"],
        )

        assert error.file_path == "/test.txt"
        assert error.conflicting_ranges == [(1, 5), (3, 10)]
        assert error.edit_ids == ["edit-1", "edit-2"]
        assert "overlapping" in str(error).lower()

    def test_conflict_error_message(self) -> None:
        """EditConflictError message should include file path and ranges."""
        error = EditConflictError(
            file_path="/path/to/file.py",
            conflicting_ranges=[(10, 20)],
            edit_ids=["call-123"],
        )

        msg = str(error)
        assert "/path/to/file.py" in msg
        assert "[(10, 20)]" in msg


class TestEditCoalescingMiddleware:
    """Tests for EditCoalescingMiddleware."""

    def test_detection_window_default(self) -> None:
        """Default detection window should be 50ms."""
        middleware = EditCoalescingMiddleware()
        assert middleware._detection_window_ms == DEFAULT_DETECTION_WINDOW_MS
        assert DEFAULT_DETECTION_WINDOW_MS == 50

    def test_detection_window_custom(self) -> None:
        """Custom detection window should be stored."""
        middleware = EditCoalescingMiddleware(config=EditCoalescingConfig(detection_window_ms=100))
        assert middleware._detection_window_ms == 100

    def test_is_edit_tool(self) -> None:
        """_is_edit_tool should recognize edit tools."""
        middleware = EditCoalescingMiddleware()

        assert middleware._is_edit_tool("edit_file") is True
        assert middleware._is_edit_tool("edit_lines") is True
        assert middleware._is_edit_tool("insert_lines") is True
        assert middleware._is_edit_tool("delete_lines") is True
        assert middleware._is_edit_tool("read_file") is False
        assert middleware._is_edit_tool("grep") is False
        assert middleware._is_edit_tool("task") is False

    def test_extract_file_path_various_keys(self) -> None:
        """_extract_file_path should find path from various key names."""
        middleware = EditCoalescingMiddleware()

        assert middleware._extract_file_path({"path": "/a.txt"}) == "/a.txt"
        assert middleware._extract_file_path({"file_path": "/b.txt"}) == "/b.txt"
        assert middleware._extract_file_path({"filepath": "/c.txt"}) == "/c.txt"
        assert middleware._extract_file_path({"file": "/d.txt"}) == "/d.txt"
        assert middleware._extract_file_path({"other": "/e.txt"}) is None
        assert middleware._extract_file_path({}) is None

    def test_extract_file_path_empty_string(self) -> None:
        """_extract_file_path should ignore empty strings."""
        middleware = EditCoalescingMiddleware()

        assert middleware._extract_file_path({"path": ""}) is None
        assert middleware._extract_file_path({"file_path": None}) is None

    @pytest.mark.asyncio
    async def test_non_edit_tool_passes_through(self) -> None:
        """Non-edit tools should pass through without coalescing."""
        middleware = EditCoalescingMiddleware()
        request = _make_request("read_file", {"path": "/test.txt"})

        result = await middleware.awrap_tool_call(request, _make_async_handler("file content"))

        assert isinstance(result, ToolMessage)
        assert result.content == "file content"

    @pytest.mark.asyncio
    async def test_edit_tool_without_path_passes_through(self) -> None:
        """Edit tool without file path should pass through without coalescing."""
        middleware = EditCoalescingMiddleware()
        request = _make_request("edit_lines", {})  # No path

        result = await middleware.awrap_tool_call(request, _make_async_handler("edited"))

        assert isinstance(result, ToolMessage)
        assert result.content == "edited"

    @pytest.mark.asyncio
    async def test_find_overlaps_no_overlap(self) -> None:
        """_find_overlaps should return empty set for non-overlapping ranges."""
        middleware = EditCoalescingMiddleware()

        operations = [
            BatchedEditOperation("replace", 1, 5, "content", "call-1"),
            BatchedEditOperation("replace", 10, 15, "content", "call-2"),
            BatchedEditOperation("replace", 20, 25, "content", "call-3"),
        ]

        overlaps = middleware._find_overlaps(operations)
        assert overlaps == set()

    @pytest.mark.asyncio
    async def test_find_overlaps_with_overlap(self) -> None:
        """_find_overlaps should detect overlapping ranges."""
        middleware = EditCoalescingMiddleware()

        operations = [
            BatchedEditOperation("replace", 1, 10, "content", "call-1"),
            BatchedEditOperation("replace", 5, 15, "content", "call-2"),  # Overlaps with call-1
        ]

        overlaps = middleware._find_overlaps(operations)
        assert "call-1" in overlaps
        assert "call-2" in overlaps

    @pytest.mark.asyncio
    async def test_find_overlaps_adjacent_not_overlapping(self) -> None:
        """Adjacent ranges (end == start) should not be considered overlapping."""
        middleware = EditCoalescingMiddleware()

        operations = [
            BatchedEditOperation("replace", 1, 5, "content", "call-1"),
            BatchedEditOperation("replace", 6, 10, "content", "call-2"),  # Adjacent
        ]

        overlaps = middleware._find_overlaps(operations)
        assert overlaps == set()

    @pytest.mark.asyncio
    async def test_find_overlaps_only_replacements_checked(self) -> None:
        """_find_overlaps should only check replacements, not deletions or insertions."""
        middleware = EditCoalescingMiddleware()

        operations = [
            BatchedEditOperation("delete", 1, 10, "", "call-1"),
            BatchedEditOperation("delete", 5, 15, "", "call-2"),  # Would overlap if checked
            BatchedEditOperation("insert", 5, 4, "content", "call-3"),
        ]

        overlaps = middleware._find_overlaps(operations)
        assert overlaps == set()


class TestEditToolNames:
    """Tests for EDIT_TOOL_NAMES constant."""

    def test_edit_tool_names_defined(self) -> None:
        """EDIT_TOOL_NAMES should be defined."""
        assert isinstance(EDIT_TOOL_NAMES, frozenset)
        assert len(EDIT_TOOL_NAMES) >= 3

    def test_edit_tool_names_contains_expected(self) -> None:
        """EDIT_TOOL_NAMES should contain expected tool names."""
        assert "edit_file" in EDIT_TOOL_NAMES
        assert "edit_lines" in EDIT_TOOL_NAMES
        assert "insert_lines" in EDIT_TOOL_NAMES
        assert "delete_lines" in EDIT_TOOL_NAMES


class TestBatchedEditOperation:
    """Tests for BatchedEditOperation dataclass."""

    def test_to_dict(self) -> None:
        """to_dict should return all fields."""
        op = BatchedEditOperation(
            operation_type="replace",
            start_line=1,
            end_line=5,
            content="new content",
            original_call_id="call-123",
        )

        d = op.to_dict()
        assert d["operation_type"] == "replace"
        assert d["start_line"] == 1
        assert d["end_line"] == 5
        assert d["content"] == "new content"
        assert d["original_call_id"] == "call-123"

    def test_defaults(self) -> None:
        """Default values should be set correctly."""
        op = BatchedEditOperation(
            operation_type="delete",
            start_line=10,
            end_line=20,
        )

        assert op.content == ""
        assert op.original_call_id is None

    def test_frozen(self) -> None:
        """BatchedEditOperation should be immutable."""
        op = BatchedEditOperation(
            operation_type="insert",
            start_line=5,
            end_line=4,
            content="text",
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            op.content = "changed"


def test_resolve_edit_future_skips_done_future() -> None:
    """Budget-cap stream teardown must not raise when the graph already resolved the waiter."""
    loop = asyncio.new_event_loop()
    try:
        future: asyncio.Future[ToolMessage] = loop.create_future()
        future.set_result(
            ToolMessage(content="already done", tool_call_id="call-1", name="edit_file")
        )
        edit = PendingEdit(
            tool_call_id="call-1",
            tool_name="edit_file",
            file_path="/tmp/x.py",
            args={},
            result_future=future,
            handler=MagicMock(),
            request=MagicMock(),
        )
        _resolve_edit_future(
            edit,
            ToolMessage(content="late result", tool_call_id="call-1", name="edit_file"),
        )
        assert future.result().content == "already done"
    finally:
        loop.close()
