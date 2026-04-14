"""Tests for daemon MessageRouter ``models_list`` RPC."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.daemon.message_router import MessageRouter


@pytest.mark.asyncio
async def test_models_list_response_shape() -> None:
    cfg = SootheConfig()

    sent: list[tuple[Any, dict[str, Any]]] = []

    class _FakeDaemon:
        _config = cfg
        _query_running = False
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="t-models")

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    await router.dispatch("client-m", {"type": "models_list", "request_id": "rid-models"})

    assert sent
    payload = sent[-1][1]
    assert payload["type"] == "models_list_response"
    assert payload["request_id"] == "rid-models"
    models = payload.get("models", [])
    assert isinstance(models, list)
    assert payload.get("default_model") is None or isinstance(payload["default_model"], str)
