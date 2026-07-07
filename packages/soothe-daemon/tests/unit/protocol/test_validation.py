"""Tests for daemon MessageRouter ``models_list`` RPC."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from soothe.config import SootheConfig

from soothe_daemon.protocol import MessageRouter


@pytest.mark.asyncio
async def test_models_list_response_shape() -> None:
    cfg = SootheConfig()

    sent: list[tuple[Any, dict[str, Any]]] = []

    class _FakeDaemon:
        _config = cfg
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="t-models")

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    # Bypass handshake enforcement for unit tests.
    router._is_handshake_complete = lambda _cid: True  # type: ignore[method-assign]
    await router.dispatch(
        "client-m",
        {
            "proto": "1",
            "type": "request",
            "method": "models_list",
            "params": {},
            "id": "rid-models",
        },
    )

    assert sent
    payload = sent[-1][1]
    assert payload["type"] == "response"
    assert payload["id"] == "rid-models"
    models = payload["result"].get("models", [])
    assert isinstance(models, list)
    assert payload["result"].get("default_model") is None or isinstance(
        payload["result"]["default_model"], str
    )
