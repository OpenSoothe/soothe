"""``WebSocketClient.send_input`` wire payload (IG-462).

Under protocol-1, ``send_input`` delegates to ``notify("loop_input", params)``,
so the captured wire dict is the full protocol-1 envelope. These tests verify
the params carry the expected fields.
"""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.websocket import WebSocketClient


class _CapturingClient(WebSocketClient):
    """Override ``send`` so tests inspect the outgoing envelope directly."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:  # type: ignore[override]
        self.sent.append(message)


def _params(client: _CapturingClient) -> dict[str, Any]:
    """Extract the ``params`` dict from the last sent envelope."""
    msg = client.sent[-1]
    assert msg["type"] == "notification"
    assert msg["method"] == "loop_input"
    return msg.get("params") or {}


@pytest.mark.asyncio
async def test_send_input_omits_clarification_mode_by_default() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi")
    params = _params(client)
    assert params["loop_id"] == "loop-1"
    assert params["content"] == "hi"
    assert "clarification_mode" not in params


@pytest.mark.asyncio
async def test_send_input_includes_clarification_mode_when_set() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi", clarification_mode="auto")
    params = _params(client)
    assert params["clarification_mode"] == "auto"


@pytest.mark.asyncio
async def test_send_input_passes_manual_through() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi", clarification_mode="manual")
    params = _params(client)
    assert params["clarification_mode"] == "manual"


@pytest.mark.asyncio
async def test_send_input_preserves_other_fields_alongside_mode() -> None:
    client = _CapturingClient()
    await client.send_input(
        "loop-1",
        "go",
        preferred_subagent="explore",
        autonomous=True,
        max_iterations=5,
        clarification_mode="manual",
    )
    params = _params(client)
    assert params["preferred_subagent"] == "explore"
    assert params["autonomous"] is True
    assert params["max_iterations"] == 5
    assert params["clarification_mode"] == "manual"
