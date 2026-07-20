"""Tests for edit_file staging buffer and string-replacement coalescing.

Covers:
- Parallel edit_file calls to same file are coalesced into one write
- Overlapping string replacements are detected and rejected
- Staging buffer is flushed correctly after detection window
- Staging buffer eviction triggers when max_entries exceeded
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe_nano.middleware.edit_coalescing import (
    DEFAULT_DETECTION_WINDOW_MS,
    DEFAULT_STAGING_BUFFER_EVICTION_POLICY,
    DEFAULT_STAGING_BUFFER_MAX_ENTRIES,
    EDIT_TOOL_NAMES,
    EditCoalescingConfig,
    EditCoalescingMiddleware,
    StringReplacement,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _replacement(
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    tool_call_id: str = "",
) -> StringReplacement:
    return StringReplacement(
        old_string=old_string,
        new_string=new_string,
        replace_all=replace_all,
        tool_call_id=tool_call_id,
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


def _make_edit_file_request(
    file_path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    call_id: str = "edit-call",
) -> MagicMock:
    """Create a mock request for edit_file tool."""
    return _make_request(
        "edit_file",
        {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
        tool_call_id=call_id,
    )


# ---------------------------------------------------------------------------
# TestEditCoalescingConfig
# ---------------------------------------------------------------------------


class TestEditCoalescingConfig:
    """Tests for the EditCoalescingConfig dataclass."""

    def test_defaults(self) -> None:
        """Default config values should match module-level constants."""
        config = EditCoalescingConfig()
        assert config.detection_window_ms == DEFAULT_DETECTION_WINDOW_MS
        assert config.staging_buffer_max_entries == DEFAULT_STAGING_BUFFER_MAX_ENTRIES
        assert config.staging_buffer_eviction_policy == DEFAULT_STAGING_BUFFER_EVICTION_POLICY
        assert config.detection_window_ms == 50
        assert config.staging_buffer_max_entries == 64
        assert config.staging_buffer_eviction_policy == "reject_newest"

    def test_custom_values(self) -> None:
        """Custom values should be stored."""
        config = EditCoalescingConfig(
            detection_window_ms=100,
            staging_buffer_max_entries=32,
            staging_buffer_eviction_policy="evict_oldest",
        )
        assert config.detection_window_ms == 100
        assert config.staging_buffer_max_entries == 32
        assert config.staging_buffer_eviction_policy == "evict_oldest"

    def test_invalid_detection_window(self) -> None:
        """Non-positive detection_window_ms should raise ValueError."""
        with pytest.raises(ValueError, match="detection_window_ms"):
            EditCoalescingConfig(detection_window_ms=0)
        with pytest.raises(ValueError, match="detection_window_ms"):
            EditCoalescingConfig(detection_window_ms=-1)

    def test_invalid_max_entries(self) -> None:
        """Non-positive staging_buffer_max_entries should raise ValueError."""
        with pytest.raises(ValueError, match="staging_buffer_max_entries"):
            EditCoalescingConfig(staging_buffer_max_entries=0)
        with pytest.raises(ValueError, match="staging_buffer_max_entries"):
            EditCoalescingConfig(staging_buffer_max_entries=-5)

    def test_invalid_eviction_policy(self) -> None:
        """Invalid eviction policy should raise ValueError."""
        with pytest.raises(ValueError, match="staging_buffer_eviction_policy"):
            EditCoalescingConfig(staging_buffer_eviction_policy="drop_random")

    def test_middleware_accepts_config(self) -> None:
        """Middleware should accept config in constructor."""
        config = EditCoalescingConfig(
            detection_window_ms=75,
            staging_buffer_max_entries=10,
        )
        middleware = EditCoalescingMiddleware(config=config)
        assert middleware._detection_window_ms == 75
        assert middleware._config.staging_buffer_max_entries == 10

    def test_middleware_detection_window_ms_override(self) -> None:
        """Custom detection window via config should be respected."""
        middleware = EditCoalescingMiddleware(config=EditCoalescingConfig(detection_window_ms=120))
        assert middleware._detection_window_ms == 120
        assert middleware._config.staging_buffer_max_entries == DEFAULT_STAGING_BUFFER_MAX_ENTRIES

    def test_middleware_lock_registry_injected(self) -> None:
        """Middleware should accept and use injected lock registry."""
        from soothe_nano.filesystem._lock_registry import FileEditLockRegistry

        registry = FileEditLockRegistry()
        middleware = EditCoalescingMiddleware(lock_registry=registry)
        assert middleware._lock_registry is registry


# ---------------------------------------------------------------------------
# TestStringReplacement
# ---------------------------------------------------------------------------


class TestStringReplacement:
    """Tests for the StringReplacement dataclass."""

    def test_creation(self) -> None:
        """StringReplacement should store all fields."""
        sr = StringReplacement(
            old_string="foo",
            new_string="bar",
            replace_all=False,
            tool_call_id="call-1",
        )
        assert sr.old_string == "foo"
        assert sr.new_string == "bar"
        assert sr.replace_all is False
        assert sr.tool_call_id == "call-1"

    def test_defaults(self) -> None:
        """Default values should be set."""
        sr = StringReplacement(old_string="a", new_string="b")
        assert sr.replace_all is False
        assert sr.tool_call_id == ""


# ---------------------------------------------------------------------------
# TestEditFileInToolNames
# ---------------------------------------------------------------------------


class TestEditFileInToolNames:
    """Verify edit_file is in EDIT_TOOL_NAMES."""

    def test_edit_file_is_coalesced(self) -> None:
        """edit_file should be in EDIT_TOOL_NAMES for coalescing."""
        assert "edit_file" in EDIT_TOOL_NAMES

    def test_is_edit_tool_recognizes_edit_file(self) -> None:
        """_is_edit_tool should recognize edit_file."""
        middleware = EditCoalescingMiddleware()
        assert middleware._is_edit_tool("edit_file") is True


# ---------------------------------------------------------------------------
# TestStagingBufferCoalescing
# ---------------------------------------------------------------------------


class TestStagingBufferCoalescing:
    """Tests that parallel edit_file calls to same file are coalesced."""

    @pytest.mark.asyncio
    async def test_parallel_edit_file_coalesced_into_one_write(self, tmp_path: object) -> None:
        """Two parallel edit_file calls to same file should produce one write."""
        file_path = str(tmp_path / "test_coalesce.txt")  # type: ignore[operator]
        # Write initial content
        with open(file_path, "w") as f:
            f.write("alpha\nbeta\ngamma\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=50),
        )

        # Track write calls
        write_count = 0
        original_atomic_write = middleware._atomic_write

        async def counting_write(path: str, content: str) -> None:
            nonlocal write_count
            write_count += 1
            await original_atomic_write(path, content)

        middleware._atomic_write = counting_write  # type: ignore[assignment]

        request1 = _make_edit_file_request(file_path, "alpha", "ALPHA", call_id="call-1")
        request2 = _make_edit_file_request(file_path, "beta", "BETA", call_id="call-2")

        # Launch both concurrently
        results = await asyncio.gather(
            middleware.awrap_tool_call(request1, _make_async_handler()),
            middleware.awrap_tool_call(request2, _make_async_handler()),
        )

        # Should be exactly one write
        assert write_count == 1

        # Verify file content
        with open(file_path) as f:
            content = f.read()
        assert "ALPHA" in content
        assert "BETA" in content
        assert "alpha" not in content
        assert "beta" not in content

        # Both results should be ToolMessages
        for r in results:
            assert isinstance(r, ToolMessage)

    @pytest.mark.asyncio
    async def test_single_edit_file_passes_through_handler(self, tmp_path: object) -> None:
        """Single edit_file call should pass through to the direct handler."""
        file_path = str(tmp_path / "single.txt")  # type: ignore[operator]
        with open(file_path, "w") as f:
            f.write("hello world\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=30),
        )
        handler_calls = 0

        async def tracking_handler(request: Any) -> ToolMessage:
            nonlocal handler_calls
            handler_calls += 1
            return ToolMessage(
                content="direct handler result",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call["name"],
            )

        request = _make_edit_file_request(file_path, "hello", "HELLO", call_id="call-single")

        result = await middleware.awrap_tool_call(request, tracking_handler)

        assert handler_calls == 1
        assert isinstance(result, ToolMessage)
        assert result.content == "direct handler result"
        with open(file_path) as f:
            assert f.read() == "hello world\n"

    @pytest.mark.asyncio
    async def test_staging_buffer_accumulates_entries(self) -> None:
        """Staging buffer should accumulate entries during detection window."""
        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=200),
        )

        request1 = _make_edit_file_request("/tmp/test.txt", "a", "b", call_id="call-1")
        request2 = _make_edit_file_request("/tmp/test.txt", "c", "d", call_id="call-2")

        # Start both but don't wait — just trigger the pending queue
        task1 = asyncio.create_task(middleware.awrap_tool_call(request1, _make_async_handler()))
        task2 = asyncio.create_task(middleware.awrap_tool_call(request2, _make_async_handler()))

        # Give tasks time to register
        await asyncio.sleep(0.05)

        # Both should be in the staging buffer
        assert "/tmp/test.txt" in middleware._staging_buffer
        entries = middleware._staging_buffer["/tmp/test.txt"]
        assert len(entries) == 2
        assert entries[0].tool_call_id == "call-1"
        assert entries[1].tool_call_id == "call-2"

        # Cancel tasks to avoid hanging
        task1.cancel()
        task2.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
        try:
            await task2
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# TestStringOverlapDetection
# ---------------------------------------------------------------------------


class TestStringOverlapDetection:
    """Tests for string-replacement overlap detection."""

    def test_no_overlap_distinct_strings(self) -> None:
        """Non-overlapping distinct strings should not conflict."""
        middleware = EditCoalescingMiddleware()
        content = "alpha beta gamma delta"
        replacements = [
            _replacement("alpha", "ALPHA", tool_call_id="call-1"),
            _replacement("gamma", "GAMMA", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is None

    def test_overlap_nested_strings(self) -> None:
        """One old_string containing another's text should conflict."""
        middleware = EditCoalescingMiddleware()
        content = "alpha beta gamma"
        replacements = [
            _replacement("alpha beta", "X", tool_call_id="call-1"),
            _replacement("beta", "Y", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is not None
        conflicting_ids, ranges = result
        assert "call-1" in conflicting_ids
        assert "call-2" in conflicting_ids
        assert len(ranges) >= 2

    def test_overlap_same_string_different_positions(self) -> None:
        """Same old_string appearing once but in two edits should conflict."""
        middleware = EditCoalescingMiddleware()
        content = "hello world"
        # Two non-replace_all edits with the same old_string that appears once
        # Both target the same character range → overlap
        replacements = [
            _replacement("hello", "HI", tool_call_id="call-1"),
            _replacement("hello", "HEY", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is not None
        assert "call-1" in result[0]
        assert "call-2" in result[0]

    def test_same_string_multiple_occurrences_no_conflict(self) -> None:
        """Same old_string appearing multiple times should not conflict.

        The cursor-based approach assigns each edit to a different occurrence,
        simulating sequential application.
        """
        middleware = EditCoalescingMiddleware()
        content = "hello world hello world"
        replacements = [
            _replacement("hello", "HI", tool_call_id="call-1"),
            _replacement("hello", "HEY", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is None

    def test_no_overlap_adjacent_strings(self) -> None:
        """Adjacent (non-overlapping) strings should not conflict."""
        middleware = EditCoalescingMiddleware()
        content = "abcdef"
        replacements = [
            _replacement("abc", "ABC", tool_call_id="call-1"),
            _replacement("def", "DEF", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is None

    def test_replace_all_span_detection(self) -> None:
        """replace_all should use the full span for overlap detection."""
        middleware = EditCoalescingMiddleware()
        content = "aaa bbb aaa ccc aaa"
        # replace_all for "aaa" spans from first to last occurrence
        replacements = [
            _replacement("aaa", "X", replace_all=True, tool_call_id="call-1"),
            _replacement("bbb aaa", "Y", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is not None
        assert "call-1" in result[0]
        assert "call-2" in result[0]

    def test_empty_old_string_skipped(self) -> None:
        """Empty old_string entries should be skipped, not cause conflicts."""
        middleware = EditCoalescingMiddleware()
        content = "hello world"
        replacements = [
            _replacement("", "empty", tool_call_id="call-1"),
            _replacement("hello", "HELLO", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is None

    def test_string_not_in_content_skipped(self) -> None:
        """old_string not found in content should be skipped."""
        middleware = EditCoalescingMiddleware()
        content = "hello world"
        replacements = [
            _replacement("nonexistent", "X", tool_call_id="call-1"),
            _replacement("hello", "HELLO", tool_call_id="call-2"),
        ]
        result = middleware._find_string_overlaps(content, replacements)
        assert result is None

    @pytest.mark.asyncio
    async def test_overlapping_replacements_rejected_with_error(self, tmp_path: object) -> None:
        """Overlapping string replacements should produce error ToolMessages."""
        file_path = str(tmp_path / "overlap.txt")  # type: ignore[operator]
        with open(file_path, "w") as f:
            f.write("alpha beta gamma\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=30),
        )

        # "alpha beta" overlaps with "beta"
        request1 = _make_edit_file_request(file_path, "alpha beta", "X", call_id="call-1")
        request2 = _make_edit_file_request(file_path, "beta", "Y", call_id="call-2")

        results = await asyncio.gather(
            middleware.awrap_tool_call(request1, _make_async_handler()),
            middleware.awrap_tool_call(request2, _make_async_handler()),
        )

        for r in results:
            assert isinstance(r, ToolMessage)
            assert r.status == "error"
            assert "conflict" in r.content.lower() or "overlapping" in r.content.lower()

        # File should not be modified
        with open(file_path) as f:
            content = f.read()
        assert content == "alpha beta gamma\n"


# ---------------------------------------------------------------------------
# TestStagingBufferFlush
# ---------------------------------------------------------------------------


class TestStagingBufferFlush:
    """Tests that the staging buffer is flushed after the detection window."""

    @pytest.mark.asyncio
    async def test_buffer_flushed_after_window(self, tmp_path: object) -> None:
        """Staging buffer should be empty after the detection window closes."""
        file_path = str(tmp_path / "flush.txt")  # type: ignore[operator]
        with open(file_path, "w") as f:
            f.write("line1\nline2\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=30),
        )

        request = _make_edit_file_request(file_path, "line1", "LINE1", call_id="call-flush")

        await middleware.awrap_tool_call(request, _make_async_handler("pass-through"))

        assert (
            file_path not in middleware._staging_buffer
            or len(middleware._staging_buffer.get(file_path, [])) == 0
        )

    @pytest.mark.asyncio
    async def test_buffer_cleared_on_flush(self) -> None:
        """_process_after_window should clear the staging buffer."""
        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=10),
        )

        # Manually populate staging buffer and pending edits (two edits → batch path)
        middleware._staging_buffer["/fake.txt"] = [
            StringReplacement("old", "new", False, "call-1"),
            StringReplacement("other", "OTHER", False, "call-2"),
        ]
        loop = asyncio.get_running_loop()
        future1: asyncio.Future = loop.create_future()
        future2: asyncio.Future = loop.create_future()
        middleware._pending_edits["/fake.txt"] = [
            MagicMock(
                tool_call_id="call-1",
                tool_name="edit_file",
                file_path="/fake.txt",
                args={"old_string": "old", "new_string": "new"},
                result_future=future1,
                handler=_make_async_handler(),
                request=_make_edit_file_request("/fake.txt", "old", "new", call_id="call-1"),
            ),
            MagicMock(
                tool_call_id="call-2",
                tool_name="edit_file",
                file_path="/fake.txt",
                args={"old_string": "other", "new_string": "OTHER"},
                result_future=future2,
                handler=_make_async_handler(),
                request=_make_edit_file_request("/fake.txt", "other", "OTHER", call_id="call-2"),
            ),
        ]

        # Run the window processor (mock _dispatch_string_replacements to avoid FS)
        call_dispatch = False

        async def mock_dispatch(
            file_path: str,
            edits: list,
            replacements: list,
        ) -> None:
            nonlocal call_dispatch
            call_dispatch = True
            for edit in edits:
                if not edit.result_future.done():
                    edit.result_future.set_result(
                        ToolMessage(
                            content="mocked",
                            tool_call_id=edit.tool_call_id,
                            name=edit.tool_name,
                        )
                    )

        middleware._dispatch_string_replacements = mock_dispatch  # type: ignore[assignment]

        await middleware._process_after_window()

        assert call_dispatch is True
        assert len(middleware._staging_buffer) == 0
        assert len(middleware._pending_edits) == 0

    @pytest.mark.asyncio
    async def test_multiple_files_flushed_separately(self, tmp_path: object) -> None:
        """Edits to different files should be flushed separately."""
        file_a = str(tmp_path / "a.txt")  # type: ignore[operator]
        file_b = str(tmp_path / "b.txt")  # type: ignore[operator]
        with open(file_a, "w") as f:
            f.write("content_a\n")
        with open(file_b, "w") as f:
            f.write("content_b\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=40),
        )

        req_a = _make_edit_file_request(file_a, "content_a", "CONTENT_A", call_id="a-1")
        req_b = _make_edit_file_request(file_b, "content_b", "CONTENT_B", call_id="b-1")

        results = await asyncio.gather(
            middleware.awrap_tool_call(req_a, _make_async_handler("ok-a")),
            middleware.awrap_tool_call(req_b, _make_async_handler("ok-b")),
        )

        assert all(isinstance(r, ToolMessage) for r in results)


# ---------------------------------------------------------------------------
# TestStagingBufferEviction
# ---------------------------------------------------------------------------


class TestStagingBufferEviction:
    """Tests for staging buffer eviction when max_entries is exceeded."""

    @pytest.mark.asyncio
    async def test_reject_newest_policy(self) -> None:
        """reject_newest policy should reject the entry that exceeds capacity."""
        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(
                detection_window_ms=500,
                staging_buffer_max_entries=2,
                staging_buffer_eviction_policy="reject_newest",
            ),
        )

        # Fill buffer to capacity
        middleware._lock = asyncio.Lock()
        req1 = _make_edit_file_request("/test.txt", "a", "b", call_id="c1")
        req2 = _make_edit_file_request("/test.txt", "c", "d", call_id="c2")
        req3 = _make_edit_file_request("/test.txt", "e", "f", call_id="c3")

        # Submit first two
        task1 = asyncio.create_task(middleware.awrap_tool_call(req1, _make_async_handler()))
        task2 = asyncio.create_task(middleware.awrap_tool_call(req2, _make_async_handler()))
        await asyncio.sleep(0.02)

        # Third should be rejected
        task3 = asyncio.create_task(middleware.awrap_tool_call(req3, _make_async_handler()))

        # Wait for task3 to complete (it should return quickly with error)
        result3 = await asyncio.wait_for(task3, timeout=2.0)

        assert isinstance(result3, ToolMessage)
        assert result3.status == "error"
        assert "buffer full" in result3.content.lower() or "full" in result3.content.lower()

        # Buffer should still have only 2 entries
        entries = middleware._staging_buffer.get("/test.txt", [])
        assert len(entries) == 2

        # Clean up
        task1.cancel()
        task2.cancel()
        for t in (task1, task2):
            try:
                await t
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_evict_oldest_policy(self) -> None:
        """evict_oldest policy should drop the oldest entry when capacity exceeded."""
        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(
                detection_window_ms=500,
                staging_buffer_max_entries=2,
                staging_buffer_eviction_policy="evict_oldest",
            ),
        )

        middleware._lock = asyncio.Lock()

        req1 = _make_edit_file_request("/test.txt", "a", "b", call_id="c1")
        req2 = _make_edit_file_request("/test.txt", "c", "d", call_id="c2")
        req3 = _make_edit_file_request("/test.txt", "e", "f", call_id="c3")

        task1 = asyncio.create_task(middleware.awrap_tool_call(req1, _make_async_handler()))
        task2 = asyncio.create_task(middleware.awrap_tool_call(req2, _make_async_handler()))
        await asyncio.sleep(0.02)

        # Third entry should evict the oldest (c1)
        task3 = asyncio.create_task(middleware.awrap_tool_call(req3, _make_async_handler()))
        await asyncio.sleep(0.02)

        entries = middleware._staging_buffer.get("/test.txt", [])
        assert len(entries) == 2
        # The oldest (c1) should be evicted, c2 and c3 should remain
        call_ids = [e.tool_call_id for e in entries]
        assert "c1" not in call_ids
        assert "c2" in call_ids
        assert "c3" in call_ids

        # Clean up
        for t in (task1, task2, task3):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_eviction_threshold_exact(self) -> None:
        """Entries up to max_entries should be accepted without eviction."""
        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(
                detection_window_ms=500,
                staging_buffer_max_entries=3,
                staging_buffer_eviction_policy="reject_newest",
            ),
        )

        middleware._lock = asyncio.Lock()

        # Submit exactly 3 entries (should all be accepted)
        tasks = []
        for i in range(3):
            req = _make_edit_file_request("/test.txt", f"old{i}", f"new{i}", call_id=f"call-{i}")
            tasks.append(
                asyncio.create_task(middleware.awrap_tool_call(req, _make_async_handler()))
            )

        await asyncio.sleep(0.05)

        entries = middleware._staging_buffer.get("/test.txt", [])
        assert len(entries) == 3

        for t in tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    def test_default_eviction_policy_is_reject_newest(self) -> None:
        """Default eviction policy should be reject_newest."""
        config = EditCoalescingConfig()
        assert config.staging_buffer_eviction_policy == "reject_newest"

    def test_default_max_entries_is_64(self) -> None:
        """Default staging_buffer_max_entries should be 64."""
        config = EditCoalescingConfig()
        assert config.staging_buffer_max_entries == 64


# ---------------------------------------------------------------------------
# TestFileEditLockRegistryIntegration
# ---------------------------------------------------------------------------


class TestFileEditLockRegistryIntegration:
    """Tests that FileEditLockRegistry serializes batch dispatch."""

    @pytest.mark.asyncio
    async def test_lock_registry_used_in_batch_dispatch(self, tmp_path: object) -> None:
        """Batch dispatch should acquire the per-file lock from the registry."""
        file_path = str(tmp_path / "locked.txt")  # type: ignore[operator]
        with open(file_path, "w") as f:
            f.write("alpha\nbeta\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=30),
        )

        acquire_called = False
        original_acquire = middleware._lock_registry.acquire

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def spy_acquire(path):
            nonlocal acquire_called
            acquire_called = True
            async with original_acquire(path):
                yield

        middleware._lock_registry.acquire = spy_acquire  # type: ignore[assignment]

        request1 = _make_edit_file_request(file_path, "alpha", "ALPHA", call_id="lock-1")
        request2 = _make_edit_file_request(file_path, "beta", "BETA", call_id="lock-2")
        await asyncio.gather(
            middleware.awrap_tool_call(request1, _make_async_handler()),
            middleware.awrap_tool_call(request2, _make_async_handler()),
        )

        assert acquire_called is True

        with open(file_path) as f:
            content = f.read()
        assert "ALPHA" in content
        assert "BETA" in content

    @pytest.mark.asyncio
    async def test_external_lock_registry_accepted(self) -> None:
        """Middleware should accept an externally provided lock registry."""
        from soothe_nano.filesystem._lock_registry import FileEditLockRegistry

        registry = FileEditLockRegistry()
        middleware = EditCoalescingMiddleware(lock_registry=registry)
        assert middleware._lock_registry is registry


class TestBatchEditErrorSignals:
    """Tests for per-edit error signaling in batched string replacement."""

    @pytest.mark.asyncio
    async def test_batch_partial_miss_returns_per_edit_errors(self, tmp_path: object) -> None:
        file_path = str(tmp_path / "partial.txt")  # type: ignore[operator]
        with open(file_path, "w") as f:
            f.write("alpha beta\n")

        middleware = EditCoalescingMiddleware(
            config=EditCoalescingConfig(detection_window_ms=30),
        )
        req_ok = _make_edit_file_request(file_path, "alpha", "ALPHA", call_id="ok-1")
        req_bad = _make_edit_file_request(file_path, "missing", "X", call_id="bad-1")
        ok_result, bad_result = await asyncio.gather(
            middleware.awrap_tool_call(req_ok, _make_async_handler()),
            middleware.awrap_tool_call(req_bad, _make_async_handler()),
        )
        assert isinstance(ok_result, ToolMessage)
        assert isinstance(bad_result, ToolMessage)
        assert bad_result.status == "error"
        assert "EDIT_OLD_STRING_NOT_FOUND" in str(bad_result.content)
        with open(file_path) as f:
            assert "ALPHA" in f.read()


class TestWorkspaceBackendIntegration:
    """Tests for workspace-context backend usage in batched edit paths."""

    @pytest.mark.asyncio
    async def test_read_file_for_batch_uses_backend_file_data(self) -> None:
        middleware = EditCoalescingMiddleware()

        class _BackendResult:
            error = None
            file_data = {"content": "from-backend"}

        class _Backend:
            async def aread(self, path: str) -> _BackendResult:
                assert path == "/tmp/test.txt"
                return _BackendResult()

        middleware._get_context_backend = lambda: _Backend()  # type: ignore[assignment]
        content = await middleware._read_file_for_batch("/tmp/test.txt")
        assert content == "from-backend"

    @pytest.mark.asyncio
    async def test_get_context_backend_uses_cached_workspace_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: object,
    ) -> None:
        from soothe_nano.workspace.workspace_runtime import (
            reset_workspace_context,
            set_workspace_context,
        )

        middleware = EditCoalescingMiddleware()
        sentinel_backend = object()
        captured: dict[str, object] = {}

        def _fake_get_workspace_backend(*, workspace, virtual_mode, max_file_size_mb=10):
            captured["workspace"] = workspace
            captured["virtual_mode"] = virtual_mode
            captured["max_file_size_mb"] = max_file_size_mb
            return sentinel_backend

        monkeypatch.setattr(
            "soothe_nano.workspace.workspace_filesystem.get_workspace_backend",
            _fake_get_workspace_backend,
        )

        token = set_workspace_context(workspace=tmp_path, virtual_mode=True)  # type: ignore[arg-type]
        try:
            backend = middleware._get_context_backend()
            assert backend is sentinel_backend
            assert captured["workspace"] == tmp_path
            assert captured["virtual_mode"] is True
        finally:
            reset_workspace_context(token)
