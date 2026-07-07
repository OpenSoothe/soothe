"""Tests for explicit goal_completion synthesis stream terminal markers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessageChunk
from soothe_sdk.ux.loop_stream import (
    GOAL_COMPLETION_STREAM_TERMINAL_FIELD,
    is_goal_completion_stream_terminal,
)

from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _finalize_goal_completion_stream,
    _finalize_goal_completion_streams_on_turn_end,
)


def test_is_goal_completion_stream_terminal_on_explicit_flag() -> None:
    msg = AIMessageChunk(
        content="",
        phase="goal_completion",
        **{GOAL_COMPLETION_STREAM_TERMINAL_FIELD: True},
    )
    assert is_goal_completion_stream_terminal(msg)


@pytest.mark.asyncio
async def test_empty_stream_terminal_finalizes_inflight_card() -> None:
    """Empty terminal frames must finalize synthesis UI (adaptive chunked tail)."""
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    stream_msg = MagicMock()
    stream_msg.append_content = AsyncMock()
    stream_msg.stop_stream = AsyncMock()
    stream_msg._content = "Full report already streamed."
    stream_msg._streaming_active = True
    stream_msg.id = "asst-test"

    ns_key = ()
    goal_completion_stream_by_namespace = {ns_key: stream_msg}
    start = 100.0

    terminal = AIMessageChunk(
        content="",
        phase="goal_completion",
        chunk_position="last",
        **{GOAL_COMPLETION_STREAM_TERMINAL_FIELD: True},
    )
    assert is_goal_completion_stream_terminal(terminal)

    await _finalize_goal_completion_stream(
        adapter,
        stream_msg,
        ns_key=ns_key,
        goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
        assistant_message_by_namespace={},
        extra_text="",
        goal_loop_start_monotonic=start,
        turn_start_monotonic=None,
    )

    stream_msg.append_content.assert_not_called()
    stream_msg.stop_stream.assert_awaited_once()
    assert ns_key not in goal_completion_stream_by_namespace
    adapter._set_spinner.assert_awaited_with(
        "Thinking",
        turn_start_mono=start,
    )


@pytest.mark.asyncio
async def test_duplicate_goal_completion_finalize_is_idempotent() -> None:
    """Second finalize call must not invoke stop_stream again."""
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    stream_msg = MagicMock()
    stream_msg.append_content = AsyncMock()
    stream_msg.stop_stream = AsyncMock()
    stream_msg._content = "Full report."
    stream_msg._streaming_active = True
    stream_msg.id = "asst-test"

    ns_key = ()
    goal_completion_stream_by_namespace = {ns_key: stream_msg}

    await _finalize_goal_completion_stream(
        adapter,
        stream_msg,
        ns_key=ns_key,
        goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
        assistant_message_by_namespace={},
        extra_text="",
    )
    stream_msg._streaming_active = False
    await _finalize_goal_completion_stream(
        adapter,
        stream_msg,
        ns_key=ns_key,
        goal_completion_stream_by_namespace={ns_key: stream_msg},
        assistant_message_by_namespace={},
        extra_text="",
    )
    stream_msg.stop_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_end_turn_scope_finalizes_inflight_streams() -> None:
    """``soothe.stream.end`` scope=turn must stop all inflight goal_completion cards."""
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    stream_msg = MagicMock()
    stream_msg.append_content = AsyncMock()
    stream_msg.stop_stream = AsyncMock()
    stream_msg._content = "Partial synthesis."
    stream_msg._streaming_active = True
    stream_msg.id = "asst-turn-end"

    ns_key = ()
    goal_completion_stream_by_namespace = {ns_key: stream_msg}

    await _finalize_goal_completion_streams_on_turn_end(
        adapter,
        goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
        assistant_message_by_namespace={},
        goal_loop_start_monotonic=100.0,
        turn_start_monotonic=90.0,
    )

    stream_msg.stop_stream.assert_awaited_once()
    assert ns_key not in goal_completion_stream_by_namespace
