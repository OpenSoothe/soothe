"""Unit tests for FileLockMiddleware (RFC-222)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.foundation.autopilot.engine.file_lock_registry import FileLockRegistry
from soothe.foundation.events.internal_bus import InternalEventBus, reset_internal_bus
from soothe.middleware.file_lock import FileLockMiddleware


def _make_request(
    tool_name: str,
    args: dict[str, Any],
    *,
    call_id: str = "call-1",
) -> ToolCallRequest:
    """Build a minimal ToolCallRequest for middleware tests."""
    return ToolCallRequest(
        tool_call={"id": call_id, "name": tool_name, "args": args},
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )


async def _success_handler(_req: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content="ok", tool_call_id=_req.tool_call.get("id", ""), name=_req.tool_call.get("name", "")
    )


class TestFileLockMiddleware:
    """Tests for FileLockMiddleware (langchain AgentMiddleware)."""

    def setup_method(self) -> None:
        """Reset internal bus singleton before each test."""
        reset_internal_bus()

    def test_construct(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
        )
        assert middleware._loop_id == "loop-001"
        assert middleware._goal_id == "goal-001"
        assert middleware.name == "FileLockMiddleware"

    @pytest.mark.asyncio
    async def test_non_file_tool_passes_through(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request("execute", {"command": "ls"})
        result = await middleware.awrap_tool_call(request, _success_handler)

        assert isinstance(result, ToolMessage)
        assert result.content == "ok"
        assert registry.lock_count() == 0

    @pytest.mark.asyncio
    async def test_edit_file_acquires_lock(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request(
            "edit_file", {"file_path": "/file.py", "old_string": "a", "new_string": "b"}
        )
        result = await middleware.awrap_tool_call(request, _success_handler)

        assert isinstance(result, ToolMessage)
        assert result.content == "ok"
        assert registry.is_locked("/file.py")
        lock = registry.get_lock("/file.py")
        assert lock is not None
        assert lock.loop_id == "loop-001"
        assert lock.operation == "edit"

    @pytest.mark.asyncio
    async def test_write_file_acquires_write_lock(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request("write_file", {"file_path": "/new.py", "content": "x"})
        await middleware.awrap_tool_call(request, _success_handler)

        lock = registry.get_lock("/new.py")
        assert lock is not None
        assert lock.operation == "write"

    @pytest.mark.asyncio
    async def test_delete_file_acquires_delete_lock(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request("delete_file", {"path": "/old.py"})
        await middleware.awrap_tool_call(request, _success_handler)

        lock = registry.get_lock("/old.py")
        assert lock is not None
        assert lock.operation == "delete"

    @pytest.mark.asyncio
    async def test_read_file_not_intercepted(self) -> None:
        """read_file is not a write op; should pass through with no lock."""
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request("read_file", {"path": "/file.py"})
        result = await middleware.awrap_tool_call(request, _success_handler)

        assert isinstance(result, ToolMessage)
        assert not registry.is_locked("/file.py")

    @pytest.mark.asyncio
    async def test_conflict_returns_tool_message_error(self) -> None:
        """Conflict yields a ToolMessage(status=error) instead of raising."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file.py", "goal-002", "loop-002", "edit")

        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        called = {"handler": False}

        async def handler(_req: ToolCallRequest) -> ToolMessage:
            called["handler"] = True
            return ToolMessage(content="ok", tool_call_id="call-1", name="edit_file")

        request = _make_request("edit_file", {"file_path": "/file.py"})
        result = await middleware.awrap_tool_call(request, handler)

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "file_conflict" in str(result.content)
        assert "goal-002" in str(result.content)
        assert "loop-002" in str(result.content)
        assert called["handler"] is False  # handler must not run on conflict

    @pytest.mark.asyncio
    async def test_same_loop_can_re_edit(self) -> None:
        """Same loop already owns the lock — no conflict, handler runs."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file.py", "goal-001", "loop-001", "edit")

        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        request = _make_request("edit_file", {"file_path": "/file.py"})
        result = await middleware.awrap_tool_call(request, _success_handler)

        assert isinstance(result, ToolMessage)
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_path_key_variations(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        await middleware.awrap_tool_call(
            _make_request("edit_file", {"path": "/a.py"}), _success_handler
        )
        await middleware.awrap_tool_call(
            _make_request("edit_file", {"file_path": "/b.py"}), _success_handler
        )
        await middleware.awrap_tool_call(
            _make_request("edit_file", {"filepath": "/c.py"}), _success_handler
        )
        await middleware.awrap_tool_call(
            _make_request("edit_file", {"file": "/d.py"}), _success_handler
        )

        assert registry.is_locked("/a.py")
        assert registry.is_locked("/b.py")
        assert registry.is_locked("/c.py")
        assert registry.is_locked("/d.py")

    @pytest.mark.asyncio
    async def test_release_all_locks(self) -> None:
        registry = FileLockRegistry()
        middleware = FileLockMiddleware(
            file_registry=registry, loop_id="loop-001", goal_id="goal-001"
        )

        await middleware.awrap_tool_call(
            _make_request("edit_file", {"path": "/file1.py"}), _success_handler
        )
        await middleware.awrap_tool_call(
            _make_request("edit_file", {"path": "/file2.py"}), _success_handler
        )
        assert registry.lock_count() == 2

        released = await middleware.release_all_locks()
        assert sorted(released) == ["/file1.py", "/file2.py"]
        assert registry.lock_count() == 0

    @pytest.mark.asyncio
    async def test_emits_locked_event(self) -> None:
        registry = FileLockRegistry()
        bus = InternalEventBus()
        received: list[Any] = []

        async def handler(event: Any) -> None:
            received.append(event)

        bus.subscribe("soothe.internal.file.locked", handler)
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
            internal_bus=bus,
        )

        request = _make_request("edit_file", {"path": "/file.py"})
        await middleware.awrap_tool_call(request, _success_handler)

        assert len(received) == 1
        evt = received[0]
        assert evt.file_path == "/file.py"
        assert evt.loop_id == "loop-001"
        assert evt.goal_id == "goal-001"

    @pytest.mark.asyncio
    async def test_emits_conflict_event(self) -> None:
        registry = FileLockRegistry()
        registry.acquire_lock("/file.py", "goal-002", "loop-002", "edit")

        bus = InternalEventBus()
        received: list[Any] = []

        async def handler(event: Any) -> None:
            received.append(event)

        bus.subscribe("soothe.internal.file.conflict", handler)
        middleware = FileLockMiddleware(
            file_registry=registry,
            loop_id="loop-001",
            goal_id="goal-001",
            internal_bus=bus,
        )

        request = _make_request("edit_file", {"path": "/file.py"})
        result = await middleware.awrap_tool_call(request, _success_handler)

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert len(received) == 1
        evt = received[0]
        assert evt.file_path == "/file.py"
        assert evt.blocking_goal_id == "goal-002"
        assert evt.blocking_loop_id == "loop-002"
