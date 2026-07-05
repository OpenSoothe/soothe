"""Regression: trivial fast-path streams many chunks; must not use instant mount."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.tui.textual_adapter import (
    _INSTANT_LOOP_ASSISTANT_PHASES,
    _retain_assistant_ns_on_chunk_last,
    _try_mount_instant_loop_assistant_phase,
)


def test_trivial_phase_excluded_from_instant_mount_set() -> None:
    """Trivial intake streams AIMessageChunks; instant mount creates one card per chunk."""
    assert "trivial" not in _INSTANT_LOOP_ASSISTANT_PHASES


def test_retain_assistant_ns_on_chunk_last_for_loop_phases() -> None:
    assert (
        _retain_assistant_ns_on_chunk_last(
            AIMessageChunk(content="x", phase="trivial"),
            ns_key=(),
            assistant_message_by_namespace={},
            is_main_agent=True,
        )
        is True
    )
    ns = {(): object()}
    assert (
        _retain_assistant_ns_on_chunk_last(
            AIMessageChunk(content="x"),
            ns_key=(),
            assistant_message_by_namespace=ns,
            is_main_agent=True,
        )
        is True
    )
    assert (
        _retain_assistant_ns_on_chunk_last(
            AIMessageChunk(content="x"),
            ns_key=(),
            assistant_message_by_namespace={},
            is_main_agent=True,
        )
        is False
    )


@pytest.mark.asyncio
async def test_try_mount_instant_loop_assistant_phase_skips_trivial_stream() -> None:
    """Streaming trivial chunks must fall through to append_content path."""
    adapter = MagicMock()
    adapter._mount_message = AsyncMock()
    adapter._set_active_message = MagicMock()
    adapter._set_spinner = AsyncMock()

    message = AIMessageChunk(content="上", phase="trivial")
    blocks = [{"type": "text", "text": "上"}]
    ev_stats = MagicMock()

    handled = await _try_mount_instant_loop_assistant_phase(
        adapter,
        message=message,
        blocks=blocks,
        ns_key=(),
        is_main_agent=True,
        suppress_main_agent_assistant_text=False,
        pending_text_by_namespace={},
        assistant_message_by_namespace={},
        router=MagicMock(),
        ev_stats=ev_stats,
        clarification_pending=False,
    )

    assert handled is False
    adapter._mount_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_instant_mount_appends_streaming_chunks_to_one_card() -> None:
    """plan_direct / quiz streams must not mount a new card per chunk."""
    adapter = MagicMock()
    adapter._mount_message = AsyncMock()
    adapter._set_active_message = MagicMock()
    adapter._sync_message_content = MagicMock()
    ns: dict = {}
    blocks_a = [{"type": "text", "text": "Hello"}]
    blocks_b = [{"type": "text", "text": " world"}]
    msg_a = AIMessageChunk(content="Hello", phase="plan_direct")
    msg_b = AIMessageChunk(content=" world", phase="plan_direct", chunk_position="last")
    ev_stats = MagicMock()

    handled_a = await _try_mount_instant_loop_assistant_phase(
        adapter,
        message=msg_a,
        blocks=blocks_a,
        ns_key=(),
        is_main_agent=True,
        suppress_main_agent_assistant_text=False,
        pending_text_by_namespace={},
        assistant_message_by_namespace=ns,
        router=MagicMock(),
        ev_stats=ev_stats,
        clarification_pending=False,
    )
    assert handled_a is True
    adapter._mount_message.assert_awaited_once()
    card = ns[()]
    assert card._content == "Hello"

    handled_b = await _try_mount_instant_loop_assistant_phase(
        adapter,
        message=msg_b,
        blocks=blocks_b,
        ns_key=(),
        is_main_agent=True,
        suppress_main_agent_assistant_text=False,
        pending_text_by_namespace={},
        assistant_message_by_namespace=ns,
        router=MagicMock(),
        ev_stats=ev_stats,
        clarification_pending=False,
    )
    assert handled_b is True
    adapter._mount_message.assert_awaited_once()
    assert card._content == "Hello world"
