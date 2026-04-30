"""Integration tests for daemon input with image attachments (IG-327)."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from soothe_sdk.client import WebSocketClient

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    get_base_config,
)

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _build_daemon_config(tmp_path: Path, port: int) -> SootheConfig:
    base_config = get_base_config()

    return SootheConfig(
        providers=base_config.providers,
        router=base_config.router,
        vector_stores=base_config.vector_stores,
        vector_store_router=base_config.vector_store_router,
        persistence={"persist_dir": str(tmp_path / "persistence")},
        protocols={
            "memory": {"enabled": False},
            "durability": {
                "backend": "sqlite",
                "persist_dir": str(tmp_path / "durability"),
            },
        },
        daemon={
            "transports": {
                "unix_socket": {"enabled": False},
                "websocket": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": port,
                    "cors_origins": ["*"],
                    "tls_enabled": False,
                },
                "http_rest": {"enabled": False},
            },
        },
    )


@pytest_asyncio.fixture
async def websocket_daemon_patched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Start daemon with vision preflight stubbed (no image-model API call)."""
    vision_calls: list[dict[str, Any]] = []

    async def _fake_enrich(
        config: Any,
        text: str,
        attachments: list[dict[str, str]],
    ) -> str:
        vision_calls.append({"text": text, "n": len(attachments)})
        return f"{text}\n--- Vision summary ---\nstub-vision\n---\n"

    monkeypatch.setattr(
        "soothe.daemon.query_engine.enrich_user_text_with_vision",
        _fake_enrich,
        raising=True,
    )

    port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, port, vision_calls
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_input_with_image_runs_turn(
    websocket_daemon_patched: tuple[SootheDaemon, int, list[dict[str, Any]]],
) -> None:
    daemon, port, vision_calls = websocket_daemon_patched
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    try:
        await client.send({"type": "thread_create", "metadata": {}})
        created = await await_event_type(client.read_event, "thread_created", timeout=8.0)
        thread_id = created["thread_id"]
        assert thread_id

        await client.send({"type": "resume_thread", "thread_id": thread_id})
        resume = await await_event_type(client.read_event, "status", timeout=8.0)
        assert resume.get("thread_resumed") is True

        await client.send(
            {
                "type": "input",
                "text": "ack",
                "interactive": True,
                "attachments": [{"mime_type": "image/png", "data": TINY_PNG_B64}],
            }
        )
        running = await await_status_state(client.read_event, "running", timeout=8.0)
        assert running.get("state") == "running"
        await await_status_state(client.read_event, "idle", timeout=120.0)

        assert len(vision_calls) == 1
        assert vision_calls[0]["text"] == "ack"
        assert vision_calls[0]["n"] == 1
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_input_invalid_attachment_returns_error(
    tmp_path: Path,
) -> None:
    port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.2)
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    try:
        await client.send({"type": "thread_create", "metadata": {}})
        created = await await_event_type(client.read_event, "thread_created", timeout=8.0)
        thread_id = created["thread_id"]
        await client.send({"type": "resume_thread", "thread_id": thread_id})
        await await_event_type(client.read_event, "status", timeout=8.0)

        await client.send(
            {
                "type": "input",
                "text": "x",
                "attachments": [{"mime_type": "image/png", "data": "!!!"}],
            }
        )
        err = await await_event_type(client.read_event, "error", timeout=5.0)
        assert err.get("code") == "INVALID_MESSAGE"
    finally:
        if client.is_connected:
            await client.close()
        with contextlib.suppress(Exception):
            await daemon.stop()
