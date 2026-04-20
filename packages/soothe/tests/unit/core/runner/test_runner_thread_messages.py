"""Tests for thread-message passthrough helpers on `SootheRunner`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.runner import SootheRunner


@pytest.mark.asyncio
async def test_get_persisted_thread_messages_forwards_include_events() -> None:
    """Runner should forward include-events flag to thread context manager."""
    runner = object.__new__(SootheRunner)
    get_thread_messages = AsyncMock(return_value=[{"kind": "event"}])
    manager = SimpleNamespace(get_thread_messages=get_thread_messages)
    runner.thread_context_manager = MagicMock(return_value=manager)

    result = await runner.get_persisted_thread_messages(
        "thread-1",
        limit=25,
        offset=4,
        include_events=True,
    )

    assert result == [{"kind": "event"}]
    get_thread_messages.assert_awaited_once_with(
        "thread-1",
        limit=25,
        offset=4,
        include_events=True,
    )
