"""``WebSocketClient.send_input`` wire payload (IG-462)."""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.websocket import WebSocketClient


class _CapturingClient(WebSocketClient):
    """Override ``send`` so tests inspect the outgoing payload directly."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: dict[str, Any]) -> None:  # type: ignore[override]
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_send_input_omits_clarification_mode_by_default() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi")
    payload = client.sent[-1]
    assert payload["type"] == "loop_input"
    assert "clarification_mode" not in payload


@pytest.mark.asyncio
async def test_send_input_includes_clarification_mode_when_set() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi", clarification_mode="auto")
    payload = client.sent[-1]
    assert payload["clarification_mode"] == "auto"


@pytest.mark.asyncio
async def test_send_input_passes_manual_through() -> None:
    client = _CapturingClient()
    await client.send_input("loop-1", "hi", clarification_mode="manual")
    payload = client.sent[-1]
    assert payload["clarification_mode"] == "manual"


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
    payload = client.sent[-1]
    assert payload["preferred_subagent"] == "explore"
    assert payload["autonomous"] is True
    assert payload["max_iterations"] == 5
    assert payload["clarification_mode"] == "manual"
