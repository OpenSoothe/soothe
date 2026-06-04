"""``WebSocketClient.invoke_skill`` wire payload (RFC-622).

Without ``clarification_mode`` in the outgoing payload, slash-skill turns
silently fall back to the daemon's configured default (typically auto), so
veritas runs even when the operator selected Manual.
"""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.websocket import WebSocketClient


class _CapturingClient(WebSocketClient):
    """Capture ``invoke_skill`` payloads without driving real I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def request_response(  # type: ignore[override]
        self,
        payload: dict[str, Any],
        *,
        response_type: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        self.sent.append(payload)
        return {"type": response_type, "echo": {}}


@pytest.mark.asyncio
async def test_invoke_skill_omits_clarification_mode_by_default() -> None:
    client = _CapturingClient()
    await client.invoke_skill("my-skill", "hello")
    payload = client.sent[-1]
    assert payload["type"] == "invoke_skill"
    assert payload["skill"] == "my-skill"
    assert payload["args"] == "hello"
    assert "clarification_mode" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "auto"])
async def test_invoke_skill_includes_clarification_mode_when_set(mode: str) -> None:
    client = _CapturingClient()
    await client.invoke_skill("my-skill", "", clarification_mode=mode)
    payload = client.sent[-1]
    assert payload["clarification_mode"] == mode
