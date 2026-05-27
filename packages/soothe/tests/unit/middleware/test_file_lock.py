"""Unit tests for FileLockMiddleware (RFC-222, IG-295)."""

import pytest

from soothe.core.events.internal_bus import InternalEventBus, reset_internal_bus
from soothe.core.goal_engine.file_lock_registry import (
    FileConflictError,
    FileLockRegistry,
)
from soothe.middleware.file_lock import FileLockMiddleware, create_file_lock_middleware


class TestFileLockMiddleware:
    """Tests for FileLockMiddleware class."""

    def setup_method(self) -> None:
        """Reset internal bus before each test."""
        reset_internal_bus()

    def test_create_middleware(self) -> None:
        """Test basic middleware creation."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        assert middleware._loop_id == "loop-001"
        assert middleware._goal_id == "goal-001"

    def test_factory_function(self) -> None:
        """Test create_file_lock_middleware factory."""
        registry = FileLockRegistry()
        middleware = create_file_lock_middleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        assert middleware._loop_id == "loop-001"

    @pytest.mark.asyncio
    async def test_intercept_non_file_tool(self) -> None:
        """Test that non-file tools pass through."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        result = await middleware.intercept_tool_call(
            tool_name="execute",
            tool_input={"command": "ls"},
        )

        assert result == {"command": "ls"}
        assert registry.lock_count() == 0

    @pytest.mark.asyncio
    async def test_intercept_edit_file_no_conflict(self) -> None:
        """Test edit_file acquires lock when no conflict."""
        registry = FileLockRegistry()
        bus = InternalEventBus()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
            internal_bus=bus,
        )

        result = await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file.py", "old_string": "a", "new_string": "b"},
        )

        assert result == {"path": "/file.py", "old_string": "a", "new_string": "b"}
        assert registry.is_locked("/file.py")
        assert registry.get_lock("/file.py").loop_id == "loop-001"

    @pytest.mark.asyncio
    async def test_intercept_write_file_no_conflict(self) -> None:
        """Test write_file acquires lock when no conflict."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        await middleware.intercept_tool_call(
            tool_name="write_file",
            tool_input={"path": "/new_file.py", "content": "test"},
        )

        assert registry.is_locked("/new_file.py")
        lock = registry.get_lock("/new_file.py")
        assert lock.operation == "write"

    @pytest.mark.asyncio
    async def test_intercept_delete_file_no_conflict(self) -> None:
        """Test delete_file acquires lock when no conflict."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        await middleware.intercept_tool_call(
            tool_name="delete_file",
            tool_input={"path": "/old_file.py"},
        )

        assert registry.is_locked("/old_file.py")
        lock = registry.get_lock("/old_file.py")
        assert lock.operation == "delete"

    @pytest.mark.asyncio
    async def test_intercept_read_file_no_lock(self) -> None:
        """Test read_file does not acquire lock."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        await middleware.intercept_tool_call(
            tool_name="read_file",
            tool_input={"path": "/file.py"},
        )

        assert not registry.is_locked("/file.py")

    @pytest.mark.asyncio
    async def test_intercept_conflict_raises_error(self) -> None:
        """Test conflict with different loop raises FileConflictError."""
        registry = FileLockRegistry()
        # Lock by different loop
        registry.acquire_lock("/file.py", "goal-002", "loop-002", "edit")

        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        with pytest.raises(FileConflictError) as exc_info:
            await middleware.intercept_tool_call(
                tool_name="edit_file",
                tool_input={"path": "/file.py", "old_string": "a", "new_string": "b"},
            )

        assert exc_info.value.file_path == "/file.py"
        assert exc_info.value.blocking_goal_id == "goal-002"
        assert exc_info.value.blocking_loop_id == "loop-002"

    @pytest.mark.asyncio
    async def test_same_loop_allowed(self) -> None:
        """Test same loop can edit locked file."""
        registry = FileLockRegistry()
        # Lock by same loop
        registry.acquire_lock("/file.py", "goal-001", "loop-001", "edit")

        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        # Should not raise - same loop owns the lock
        result = await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file.py", "old_string": "a", "new_string": "b"},
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_extract_path_variations(self) -> None:
        """Test path extraction from various input formats."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        # Test 'path' key
        await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file1.py"},
        )
        assert registry.is_locked("/file1.py")

        # Test 'file_path' key
        await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"file_path": "/file2.py"},
        )
        assert registry.is_locked("/file2.py")

    @pytest.mark.asyncio
    async def test_release_all_locks(self) -> None:
        """Test releasing all locks for goal."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )

        # Acquire multiple locks
        await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file1.py"},
        )
        await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file2.py"},
        )

        assert registry.lock_count() == 2

        # Release all
        released = await middleware.release_all_locks()

        assert len(released) == 2
        assert "/file1.py" in released
        assert "/file2.py" in released
        assert registry.lock_count() == 0

    @pytest.mark.asyncio
    async def test_emits_locked_event(self) -> None:
        """Test that lock acquisition emits InternalFileLockedEvent."""
        registry = FileLockRegistry()
        bus = InternalEventBus()
        events_received = []

        async def handler(event: object) -> None:
            events_received.append(event)

        bus.subscribe("soothe.internal.file.locked", handler)

        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
            internal_bus=bus,
        )

        await middleware.intercept_tool_call(
            tool_name="edit_file",
            tool_input={"path": "/file.py"},
        )

        assert len(events_received) == 1
        event = events_received[0]
        assert event.file_path == "/file.py"
        assert event.loop_id == "loop-001"
        assert event.goal_id == "goal-001"

    @pytest.mark.asyncio
    async def test_emits_conflict_event(self) -> None:
        """Test that conflict emits InternalFileConflictEvent."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file.py", "goal-002", "loop-002", "edit")

        bus = InternalEventBus()
        events_received = []

        async def handler(event: object) -> None:
            events_received.append(event)

        bus.subscribe("soothe.internal.file.conflict", handler)

        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
            internal_bus=bus,
        )

        with pytest.raises(FileConflictError):
            await middleware.intercept_tool_call(
                tool_name="edit_file",
                tool_input={"path": "/file.py"},
            )

        assert len(events_received) == 1
        event = events_received[0]
        assert event.file_path == "/file.py"
        assert event.blocking_goal_id == "goal-002"
        assert event.blocking_loop_id == "loop-002"
