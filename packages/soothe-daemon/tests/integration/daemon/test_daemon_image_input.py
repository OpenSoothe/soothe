"""Integration tests for daemon input with image attachments (IG-327)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from soothe.config import SootheConfig
from soothe_sdk.client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.config import SootheDaemonConfig
from ..daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)
from ..ws_loop_client import loop_new, subscribe_loop_stream

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

# Load actual image assets for real-world integration tests
_ASSETS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "assets"


def _load_image_b64(filename: str) -> str:
    """Load image file and return base64-encoded string."""
    path = _ASSETS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Asset not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


SOOTHE_LOGO_B64: str | None = None
LOGICAL_ARCH_B64: str | None = None


def _get_soothe_logo_b64() -> str:
    """Lazy-load soothe-logo.png base64."""
    global SOOTHE_LOGO_B64
    if SOOTHE_LOGO_B64 is None:
        SOOTHE_LOGO_B64 = _load_image_b64("soothe-logo.png")
    return SOOTHE_LOGO_B64


def _get_logical_arch_b64() -> str:
    """Lazy-load logical-arch.png base64."""
    global LOGICAL_ARCH_B64
    if LOGICAL_ARCH_B64 is None:
        LOGICAL_ARCH_B64 = _load_image_b64("logical-arch.png")
    return LOGICAL_ARCH_B64


def _build_daemon_config(tmp_path: Path, port: int) -> tuple[SootheConfig, SootheDaemonConfig]:
    return build_daemon_config(tmp_path=tmp_path, websocket_port=port)


@pytest_asyncio.fixture
async def websocket_daemon_patched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Start daemon with vision preflight stubbed (no image-model API call)."""
    vision_calls: list[dict[str, Any]] = []

    async def _fake_enrich(
        config: Any,
        text: str,
        attachments: list[dict[str, str]],
        *,
        session_id: str | None = None,
    ) -> str:
        vision_calls.append({"text": text, "n": len(attachments), "session_id": session_id})
        return f"{text}\n--- Vision summary ---\nstub-vision\n---\n"

    monkeypatch.setattr(
        "soothe_daemon.query.engine.enrich_user_text_with_vision",
        _fake_enrich,
        raising=True,
    )

    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
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
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            "ack",
            attachments=[{"mime_type": "image/png", "data": TINY_PNG_B64}],
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
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.2)
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            "x",
            attachments=[{"mime_type": "image/png", "data": "!!!"}],
        )
        err = await await_event_type(client.read_event, "error", timeout=5.0)
        assert err.get("code") == "INVALID_MESSAGE"
    finally:
        if client.is_connected:
            await client.close()
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_input_with_real_image_attachment(
    websocket_daemon_patched: tuple[SootheDaemon, int, list[dict[str, Any]]],
) -> None:
    """Test agent task execution with a real image file (soothe-logo.png)."""
    daemon, port, vision_calls = websocket_daemon_patched
    _ = daemon

    soothe_logo_b64 = _get_soothe_logo_b64()

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            "Describe what you see in this image",
            attachments=[{"mime_type": "image/png", "data": soothe_logo_b64}],
        )
        running = await await_status_state(client.read_event, "running", timeout=8.0)
        assert running.get("state") == "running"
        await await_status_state(client.read_event, "idle", timeout=120.0)

        assert len(vision_calls) == 1
        assert (
            "image" in vision_calls[0]["text"].lower()
            or vision_calls[0]["text"] == "Describe what you see in this image"
        )
        assert vision_calls[0]["n"] == 1
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_input_with_multi_image_attachments(
    websocket_daemon_patched: tuple[SootheDaemon, int, list[dict[str, Any]]],
) -> None:
    """Test agent task execution with multiple image files (soothe-logo.png + logical-arch.png)."""
    daemon, port, vision_calls = websocket_daemon_patched
    _ = daemon

    soothe_logo_b64 = _get_soothe_logo_b64()
    logical_arch_b64 = _get_logical_arch_b64()

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(
            loop_id,
            "Compare these two images and describe their contents",
            attachments=[
                {"mime_type": "image/png", "data": soothe_logo_b64},
                {"mime_type": "image/png", "data": logical_arch_b64},
            ],
        )
        running = await await_status_state(client.read_event, "running", timeout=8.0)
        assert running.get("state") == "running"
        await await_status_state(client.read_event, "idle", timeout=120.0)

        assert len(vision_calls) == 1
        assert vision_calls[0]["n"] == 2
    finally:
        if client.is_connected:
            await client.close()
