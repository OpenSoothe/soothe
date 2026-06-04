"""Reattach handler test (RFC-413).

``handle_loop_reattach`` should drive ``LoopCardManager.replay_to_client``
and produce ``card.replay_begin`` → ``card.created`` × N →
``card.replay_end`` frames. RFC-411's legacy frames are no longer emitted.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe_daemon.display.loop_card_manager import (
    CARD_CREATED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    LoopCardManager,
)
from soothe_daemon.event.reattachment import handle_loop_reattach


@pytest.fixture
def loops_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SOOTHE_HOME so PersistenceDirectoryManager writes into tmp."""
    soothe_home = tmp_path / "soothe_home"
    soothe_home.mkdir()
    import soothe.config

    monkeypatch.setattr(soothe.config, "SOOTHE_HOME", str(soothe_home))
    return soothe_home / "data" / "loops"


def _patch_bind_thread(monkeypatch: pytest.MonkeyPatch, thread_id: str = "thread_x") -> None:
    import soothe_daemon.runtime.loop_dispatcher as dispatcher

    async def _fake(_daemon, _loop_id):
        return thread_id

    monkeypatch.setattr(dispatcher, "bind_execution_thread_for_loop", _fake)


_LEGACY_FRAME_TYPES = frozenset({"history_replay", "loop_reattached", "replay_complete"})


@pytest.mark.asyncio
async def test_handle_loop_reattach_streams_only_card_frames(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reattach emits card.* only — RFC-411 legacy frames are gone."""
    _patch_bind_thread(monkeypatch)
    runner = MagicMock()
    runner.get_thread_state_values = AsyncMock(
        return_value={
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="hi there"),
            ]
        }
    )
    runner.get_persisted_thread_messages = AsyncMock(return_value=[])
    daemon = SimpleNamespace(_runner=runner)
    daemon._card_manager = LoopCardManager(daemon)

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_test", daemon, client_id="client_a")

    types = [f["type"] for f in sent]
    assert types[0] == CARD_REPLAY_BEGIN
    assert types[-1] == CARD_REPLAY_END
    created_frames = [f for f in sent if f["type"] == CARD_CREATED]
    assert len(created_frames) == 2

    # No legacy frames anymore.
    for legacy in _LEGACY_FRAME_TYPES:
        assert legacy not in types, f"legacy frame {legacy} should not be emitted"

    for frame in sent:
        if "loop_id" in frame:
            assert frame["loop_id"] == "loop_test"


@pytest.mark.asyncio
async def test_handle_loop_reattach_emits_empty_card_block(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loop with no derivable data still produces a clean card.replay_* block."""
    _patch_bind_thread(monkeypatch)
    runner = MagicMock()
    runner.get_thread_state_values = AsyncMock(return_value={"messages": []})
    runner.get_persisted_thread_messages = AsyncMock(return_value=[])
    daemon = SimpleNamespace(_runner=runner)
    daemon._card_manager = LoopCardManager(daemon)

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_empty", daemon, client_id="client_b")

    types = [f["type"] for f in sent]
    assert CARD_REPLAY_BEGIN in types
    assert CARD_REPLAY_END in types
    assert not [f for f in sent if f["type"] == CARD_CREATED]
    for legacy in _LEGACY_FRAME_TYPES:
        assert legacy not in types


@pytest.mark.asyncio
async def test_handle_loop_reattach_without_card_manager_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing card manager: handler logs + returns; no legacy frames emitted."""
    daemon = SimpleNamespace()  # no _card_manager attribute

    sent: list[dict] = []

    async def fake_send(_client_id, frame):
        sent.append(frame)

    daemon._send_client_message = fake_send

    await handle_loop_reattach("loop_bare", daemon, client_id="client_c")
    types = [f["type"] for f in sent]
    # No frames at all.
    assert not types
