"""Regression: trivial fast-path streams many chunks; must not use instant mount."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.tui.textual_adapter import (
    _INSTANT_LOOP_ASSISTANT_PHASES,
    _try_mount_instant_loop_assistant_phase,
)


def test_trivial_phase_excluded_from_instant_mount_set() -> None:
    """Trivial intake streams AIMessageChunks; instant mount creates one card per chunk."""
    assert "trivial" not in _INSTANT_LOOP_ASSISTANT_PHASES


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
