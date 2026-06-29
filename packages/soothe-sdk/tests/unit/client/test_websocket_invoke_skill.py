"""``WebSocketClient.invoke_skill`` wire payload (RFC-622).

Without ``clarification_mode`` in the outgoing params, slash-skill turns
silently fall back to the daemon's configured default (typically auto), so
veritas runs even when the operator selected Manual.
"""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.websocket import WebSocketClient


class _CapturingClient(WebSocketClient):
    """Capture ``invoke_skill`` params without driving real I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(  # type: ignore[override]
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        proto: str = "1",
    ) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        return {"echo": {}}


@pytest.mark.asyncio
async def test_invoke_skill_omits_clarification_mode_by_default() -> None:
    client = _CapturingClient()
    await client.invoke_skill("my-skill", "hello")
    method, params = client.calls[-1]
    assert method == "invoke_skill"
    assert params["skill"] == "my-skill"
    assert params["args"] == "hello"
    assert "clarification_mode" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "auto"])
async def test_invoke_skill_includes_clarification_mode_when_set(mode: str) -> None:
    client = _CapturingClient()
    await client.invoke_skill("my-skill", "", clarification_mode=mode)
    method, params = client.calls[-1]
    assert params["clarification_mode"] == mode
