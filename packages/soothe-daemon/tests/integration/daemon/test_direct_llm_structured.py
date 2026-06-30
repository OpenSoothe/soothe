"""Integration tests for structured ``intent_hint=text_completion`` turns (IG-419)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import pytest
import pytest_asyncio
from soothe.config import SootheConfig
from soothe_sdk.client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.services.direct_llm_turn import run_text_completion_turn
from tests.integration.daemon._structured_direct_llm_helpers import (
    WORD_REPLY_SCHEMA,
    await_messages_assistant_content,
    parse_word_reply_json,
)
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)
from tests.integration.ws_loop_client import loop_new, subscribe_loop_stream


@pytest_asyncio.fixture
async def websocket_daemon_llm(tmp_path: Path):
    """Start an isolated daemon with real LLM providers from integration config."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    agent_cfg, daemon_cfg = build_daemon_config(tmp_path=tmp_path, websocket_port=port)
    daemon = SootheDaemon(agent_cfg, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.3)
    try:
        yield daemon, port, agent_cfg
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_input_rejects_response_schema_without_structured_hint(
    websocket_daemon_llm: tuple[SootheDaemon, int, SootheConfig],
) -> None:
    """Wire validation: response_schema requires text_completion or image_to_text."""
    _daemon, port, _cfg = websocket_daemon_llm
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send(
            {
                "proto": "1",
                "type": "notification",
                "method": "loop_input",
                "params": {
                    "loop_id": loop_id,
                    "content": "hello",
                    "intent_hint": "embed",
                    "response_schema": WORD_REPLY_SCHEMA,
                },
            }
        )

        deadline = asyncio.get_running_loop().time() + 15.0
        while asyncio.get_running_loop().time() < deadline:
            remaining = deadline - asyncio.get_running_loop().time()
            ev = await asyncio.wait_for(client.read_event(), timeout=max(remaining, 0.001))
            if not ev:
                continue
            if ev.get("type") == "error":
                err = ev.get("error") or {}
                assert err.get("code") == -32600  # INVALID_REQUEST
                assert "text_completion" in str(err.get("message", "")).lower()
                return
        raise AssertionError("expected INVALID_REQUEST for response_schema with intent_hint=embed")
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_run_text_completion_turn_structured_service(
    integration_config: SootheConfig,
    requires_llm_api,
) -> None:
    """Service-level structured text_completion against configured providers."""
    raw = await run_text_completion_turn(
        integration_config,
        user_text='Return JSON with the word field set exactly to "STRUCT".',
        response_schema=WORD_REPLY_SCHEMA,
        response_schema_name="WordReply",
        response_schema_strict=True,
    )
    data = parse_word_reply_json(raw)
    assert "STRUCT" in data["word"].upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_text_completion_structured_json_reply(
    websocket_daemon_llm: tuple[SootheDaemon, int, SootheConfig],
    requires_llm_api,
) -> None:
    """End-to-end: loop_input with response_schema returns JSON assistant content."""
    _daemon, port, _cfg = websocket_daemon_llm
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            'Return JSON with word set exactly to "WIRE".',
            intent_hint="text_completion",
            response_schema=WORD_REPLY_SCHEMA,
            response_schema_name="WordReply",
            response_schema_strict=True,
        )
        await await_status_state(client.read_event, "running", timeout=15.0)
        raw = await await_messages_assistant_content(client.read_event, timeout=120.0)
        await await_status_state(client.read_event, "idle", timeout=30.0)

        data = parse_word_reply_json(raw)
        assert "WIRE" in data["word"].upper()
        # Ensure response is JSON object string, not plain prose
        json.loads(raw)
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_text_completion_plain_text_without_schema(
    websocket_daemon_llm: tuple[SootheDaemon, int, SootheConfig],
    requires_llm_api,
) -> None:
    """Regression: text_completion without response_schema still returns plain text."""
    _daemon, port, _cfg = websocket_daemon_llm
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            "Reply with exactly one word: PLAIN.",
            intent_hint="text_completion",
        )
        await await_status_state(client.read_event, "running", timeout=15.0)
        raw = await await_messages_assistant_content(client.read_event, timeout=120.0)
        assert raw
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)
    finally:
        if client.is_connected:
            await client.close()
