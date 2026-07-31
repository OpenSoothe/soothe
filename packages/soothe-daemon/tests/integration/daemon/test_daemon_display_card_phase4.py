"""IG-655 Phase 4 integration: attach hydrate + multi-subscriber card seq.

These tests seed the daemon ``LoopCardManager`` (no LLM) and exercise the
WebSocket hydrate / live ``soothe.card.*`` paths that close the IG-655
acceptance checklist.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from soothe_client import WebSocketClient
from soothe_sdk.core.events import CARD_CREATED, CARD_REPLAY_BEGIN, CARD_REPLAY_END, CARD_WIRE_TYPES
from soothe_sdk.display.transcript_types import MessageType

from soothe_daemon import SootheDaemon
from soothe_daemon.display.loop_card_manager import LoopCardManager
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    stop_daemon_safely,
    unwrap_next,
)
from tests.integration.ws_loop_client import loop_new, subscribe_loop_stream

_STRUCTURAL_TYPES = frozenset(
    {
        MessageType.USER.value,
        MessageType.ASSISTANT.value,
        MessageType.STEP_PROGRESS.value,
    }
)


def _structural_log_events(*, tool_call_count: int = 2) -> list[dict[str, Any]]:
    """Cognition step events that bind a step card with tool counts."""
    return [
        {
            "kind": "event",
            "timestamp": "2026-07-27T10:00:00+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.started",
                "step_id": "IG655-01",
                "description": "inspect workspace",
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-07-27T10:00:02+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.completed",
                "step_id": "IG655-01",
                "description": "inspect workspace",
                "success": True,
                "duration_ms": 1500,
                "tool_call_count": tool_call_count,
                "summary": "Done",
            },
        },
    ]


async def _seed_structural_catalogue(
    manager: LoopCardManager,
    loop_id: str,
    *,
    tool_call_count: int = 2,
) -> None:
    """Flush a user + step(+tool counts) + assistant projection into the ledger."""
    state = manager._buffers[loop_id]  # noqa: SLF001
    state.messages = [
        HumanMessage(content="list files"),
        AIMessage(content="Here are the files."),
    ]
    state.log_events = _structural_log_events(tool_call_count=tool_call_count)
    await manager._flush_buffers_to_ledger(loop_id, state)  # noqa: SLF001


async def _connect_handshake(client: WebSocketClient) -> None:
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()


def _card_payload_from_frame(frame: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize live custom wraps and top-level reattach card frames."""
    if not isinstance(frame, dict):
        return None
    top = str(frame.get("type") or "")
    if top in CARD_WIRE_TYPES or top in {CARD_REPLAY_BEGIN, CARD_REPLAY_END}:
        return frame
    if top == "event" and isinstance(frame.get("data"), dict):
        inner = frame["data"]
        inner_type = str(inner.get("type") or "")
        if inner_type in CARD_WIRE_TYPES or inner_type.startswith("soothe.card."):
            return inner
    return None


async def _collect_live_card_frames(
    client: WebSocketClient,
    *,
    min_frames: int,
    timeout_s: float = 8.0,
) -> list[dict[str, Any]]:
    """Collect live ``soothe.card.*`` payloads until ``min_frames`` arrive."""
    out: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while len(out) < min_frames:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(client.read_event(), timeout=remaining)
        except TimeoutError:
            break
        payload = _card_payload_from_frame(unwrap_next(raw))
        if payload is None:
            continue
        if str(payload.get("type") or "") in CARD_WIRE_TYPES:
            out.append(payload)
    return out


async def _drain_briefly(client: WebSocketClient, *, seconds: float = 0.3) -> None:
    client.clear_pending_events()
    with contextlib.suppress(TimeoutError, asyncio.CancelledError):
        while True:
            await asyncio.wait_for(client.read_event(), timeout=seconds)


def _assert_structural_catalogue(cards: list[dict[str, Any]], *, tool_call_count: int) -> None:
    types = {str(c.get("type") or "") for c in cards}
    assert MessageType.USER.value in types
    assert MessageType.ASSISTANT.value in types
    assert MessageType.STEP_PROGRESS.value in types
    steps = [c for c in cards if str(c.get("type") or "") == MessageType.STEP_PROGRESS.value]
    assert steps, "expected a step_progress card"
    assert any(int(c.get("step_tool_call_count") or 0) == tool_call_count for c in steps)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_detached_attach_loop_history_shows_structural_catalogue(
    tmp_path: Path,
) -> None:
    """Detached ledger → ``loop_history_fetch`` / reattach shows catalogue + tool counts."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.2)

    tool_call_count = 2
    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_handshake(client1)
        loop_id = await loop_new(client1)
        await subscribe_loop_stream(client1, loop_id)

        await _seed_structural_catalogue(
            daemon._card_manager,
            loop_id,
            tool_call_count=tool_call_count,
        )

        # Detach original session (loop continues; no client attached).
        detach = await client1.request("loop_detach", {"loop_id": loop_id}, timeout=5.0)
        assert detach.get("success", True)
        await close_client_safely(client1)

        # New client: ``loop continue`` / attach hydrate path.
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_handshake(client2)
        history = await client2.request(
            "loop_history_fetch",
            {"loop_id": loop_id},
            timeout=5.0,
        )
        live_cards = list(history.get("live_cards") or [])
        assert live_cards, "expected live_cards after detached seed"
        _assert_structural_catalogue(live_cards, tool_call_count=tool_call_count)
        assert all(str(c.get("type") or "") in _STRUCTURAL_TYPES for c in live_cards)

        await client2.request("loop_reattach", {"loop_id": loop_id}, timeout=5.0)
        replay_cards: list[dict[str, Any]] = []
        saw_begin = False
        saw_end = False
        deadline = asyncio.get_running_loop().time() + 10.0
        while not saw_end:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                msg = "timed out waiting for soothe.card.replay.end"
                raise TimeoutError(msg)
            raw = await asyncio.wait_for(client2.read_event(), timeout=remaining)
            frame = unwrap_next(raw)
            if not isinstance(frame, dict):
                continue
            ftype = str(frame.get("type") or "")
            if ftype == CARD_REPLAY_BEGIN:
                saw_begin = True
            elif ftype == CARD_CREATED:
                replay_cards.append(frame)
            elif ftype == CARD_REPLAY_END:
                saw_end = True

        assert saw_begin
        assert saw_end
        assert replay_cards
        # Reattach emits mutation data; kinds/types must cover the structural set.
        replay_kinds = {str(f.get("kind") or "") for f in replay_cards}
        replay_types = {
            str((f.get("data") or {}).get("type") or "")
            for f in replay_cards
            if isinstance(f.get("data"), dict)
        }
        assert MessageType.USER.value in replay_kinds or MessageType.USER.value in replay_types
        assert (
            MessageType.STEP_PROGRESS.value in replay_kinds
            or MessageType.STEP_PROGRESS.value in replay_types
        )
        step_frames = [
            f
            for f in replay_cards
            if str(f.get("kind") or "") == MessageType.STEP_PROGRESS.value
            or str((f.get("data") or {}).get("type") or "") == MessageType.STEP_PROGRESS.value
        ]
        assert any(
            int((f.get("data") or {}).get("step_tool_call_count") or 0) == tool_call_count
            for f in step_frames
        )

        await close_client_safely(client2)
    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_subscribers_same_card_ids_and_ordered_seq(tmp_path: Path) -> None:
    """Two WS subscribers on one loop observe identical card ids and seq order."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.2)

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_handshake(client1)
        loop_id = await loop_new(client1)
        await subscribe_loop_stream(client1, loop_id)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_handshake(client2)
        await subscribe_loop_stream(client2, loop_id)

        await _drain_briefly(client1)
        await _drain_briefly(client2)

        # Seed after both subscribe so live ``soothe.card.*`` broadcasts reach both.
        await _seed_structural_catalogue(daemon._card_manager, loop_id, tool_call_count=3)

        # Expect at least user + step + assistant creates.
        min_frames = 3
        frames1, frames2 = await asyncio.gather(
            _collect_live_card_frames(client1, min_frames=min_frames),
            _collect_live_card_frames(client2, min_frames=min_frames),
        )

        assert len(frames1) >= min_frames
        assert len(frames2) >= min_frames

        ids1 = [str(f.get("card_id") or "") for f in frames1]
        ids2 = [str(f.get("card_id") or "") for f in frames2]
        seqs1 = [int(f.get("seq")) for f in frames1]
        seqs2 = [int(f.get("seq")) for f in frames2]

        assert all(ids1), "card_id missing on client1 frames"
        assert ids1 == ids2
        assert seqs1 == seqs2
        assert seqs1 == sorted(seqs1)
        assert len(seqs1) == len(set(seqs1))

        await close_client_safely(client1)
        await close_client_safely(client2)
    finally:
        await stop_daemon_safely(daemon)
