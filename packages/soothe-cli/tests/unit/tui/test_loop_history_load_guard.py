"""Regression tests for duplicate loop history loads on resume."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.app import SootheApp
from soothe_cli.tui.app._module_init import _LoopHistoryPayload
from soothe_cli.tui.widgets.message_store import MessageData, MessageStore, MessageType


def test_bulk_load_replace_clears_prior_entries() -> None:
    """Resume loads must replace the store rather than append duplicates."""
    store = MessageStore()
    first = MessageData(type=MessageType.USER, content="hello", id="msg-aaa")
    second = MessageData(type=MessageType.USER, content="hello again", id="msg-aaa")

    store.bulk_load([first], replace=True)
    _archived, visible = store.bulk_load([second], replace=True)

    assert store.total_count == 1
    assert visible == [second]


def test_dedupe_message_data_by_id_keeps_last_occurrence() -> None:
    """Visible window dedupe keeps the latest card per widget id."""
    older = MessageData(type=MessageType.USER, content="old", id="msg-dup")
    newer = MessageData(type=MessageType.USER, content="new", id="msg-dup")
    other = MessageData(type=MessageType.ASSISTANT, content="ok", id="msg-other")

    deduped = SootheApp._dedupe_message_data_by_id([older, other, newer])

    assert [m.id for m in deduped] == ["msg-other", "msg-dup"]
    assert deduped[-1].content == "new"


@pytest.mark.asyncio
async def test_load_loop_history_skips_duplicate_scheduled_load() -> None:
    """Second resume load for the same loop must be a no-op."""
    app = object.__new__(SootheApp)
    app._lc_loop_id = "loop_abc"
    app._loop_history_load_lock = __import__("asyncio").Lock()
    app._loop_history_loaded_for = None
    app._message_store = MessageStore()
    app._deferred_assistant_renders = __import__("collections").deque()
    app._assistant_render_drain_scheduled = False
    app._context_tokens = 0
    app._daemon_session = MagicMock()

    payload = _LoopHistoryPayload(
        [
            MessageData(type=MessageType.USER, content="weather", id="msg-user"),
        ],
        0,
    )

    container = MagicMock()
    container.mount = AsyncMock()

    app._runtime_backend_ready = MagicMock(return_value=True)
    app._clear_messages = AsyncMock()
    app._fetch_loop_history_data = AsyncMock(return_value=payload)
    app._seed_loop_token_from_checkpoint = MagicMock()
    app.query_one = MagicMock(return_value=container)
    app._mount_message = AsyncMock()
    app._schedule_loop_message_link = MagicMock()
    app._enqueue_hydrated_assistant_render = MagicMock()
    app.set_timer = MagicMock()

    await app._load_loop_history()
    assert app._loop_history_loaded_for == "loop_abc"
    app._clear_messages.assert_awaited_once()
    app._fetch_loop_history_data.assert_awaited_once()

    app._clear_messages.reset_mock()
    app._fetch_loop_history_data.reset_mock()
    await app._load_loop_history()
    app._clear_messages.assert_not_awaited()
    app._fetch_loop_history_data.assert_not_awaited()
