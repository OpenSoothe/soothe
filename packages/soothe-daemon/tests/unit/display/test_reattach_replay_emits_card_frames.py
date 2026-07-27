"""Reattach handler test (RFC-413).

``handle_loop_reattach`` should drive ``LoopCardManager.replay_to_client``
and produce ``card.replay_begin`` → ``card.created`` × N →
``card.replay_end`` frames. RFC-411's legacy frames are no longer emitted.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from soothe_sdk.core.events import (
    CARD_CREATED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
)

from soothe_daemon.display.loop_card_manager import LoopCardManager
from soothe_daemon.event.reattachment import handle_loop_reattach

_LEGACY_FRAME_TYPES = frozenset({"history_replay", "loop_reattached", "replay_complete"})


@pytest.mark.asyncio
async def test_handle_loop_reattach_streams_only_card_frames() -> None:
    daemon = SimpleNamespace(_runner=MagicMock())
    daemon._card_manager = LoopCardManager(daemon)
    state = daemon._card_manager._buffers["loop_test"]  # noqa: SLF001
    state.messages = [HumanMessage(content="hello"), AIMessage(content="hi there")]
    await daemon._card_manager._flush_buffers_to_ledger("loop_test", state)  # noqa: SLF001

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_test", daemon, client_id="client_a")

    types = [frame["type"] for frame in sent]
    assert types[0] == CARD_REPLAY_BEGIN
    assert types[-1] == CARD_REPLAY_END
    created_frames = [frame for frame in sent if frame["type"] == CARD_CREATED]
    assert len(created_frames) == 2

    for legacy in _LEGACY_FRAME_TYPES:
        assert legacy not in types

    for frame in sent:
        if "loop_id" in frame:
            assert frame["loop_id"] == "loop_test"


@pytest.mark.asyncio
async def test_handle_loop_reattach_emits_empty_card_block() -> None:
    daemon = SimpleNamespace(_runner=MagicMock())
    daemon._card_manager = LoopCardManager(daemon)

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_empty", daemon, client_id="client_b")

    types = [frame["type"] for frame in sent]
    assert CARD_REPLAY_BEGIN in types
    assert CARD_REPLAY_END in types
    assert not [frame for frame in sent if frame["type"] == CARD_CREATED]
    for legacy in _LEGACY_FRAME_TYPES:
        assert legacy not in types


@pytest.mark.asyncio
async def test_handle_loop_reattach_without_card_manager_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = SimpleNamespace()

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_bare", daemon, client_id="client_c")
    assert not sent
