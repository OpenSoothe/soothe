"""Regression tests for headless daemon thread isolation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from soothe_cli.cli.execution import daemon as daemon_exec


class _StubClient:
    """Minimal websocket client stub for run_headless_via_daemon tests."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = list(events)

    async def send_input(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            return None
        return self._events.pop(0)

    async def close(self) -> None:
        return None


class _RecorderProcessor:
    """EventProcessor stub that records processed frames."""

    events: list[dict[str, Any]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.events = []
        _RecorderProcessor.events = self.events

    def process_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_run_headless_filters_non_active_thread_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    """Headless daemon run should ignore `status/event` frames for other threads."""
    active_thread_id = "thread-main"
    leaked_text = "Hello! I'd be happy to help you with whatever you need. What can I do for you today?"

    stub_client = _StubClient(
        [
            {"type": "status", "state": "running", "thread_id": "thread-other"},
            {
                "type": "event",
                "thread_id": "thread-other",
                "mode": "messages",
                "namespace": [],
                "data": leaked_text,
            },
            {"type": "status", "state": "running", "thread_id": active_thread_id},
            {"type": "event", "thread_id": active_thread_id, "mode": "custom", "data": {"type": "ok"}},
            {"type": "status", "state": "idle", "thread_id": active_thread_id},
            {"type": "event", "thread_id": "thread-other", "mode": "custom", "data": {"type": "late"}},
            None,
        ]
    )

    async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _bootstrap(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"type": "status", "state": "idle", "thread_id": active_thread_id}

    monkeypatch.setattr(daemon_exec, "EventProcessor", _RecorderProcessor)
    monkeypatch.setattr(daemon_exec, "connect_websocket_with_retries", _noop_async)
    monkeypatch.setattr(
        daemon_exec,
        "bootstrap_thread_session",
        _bootstrap,
    )
    monkeypatch.setattr(daemon_exec, "websocket_url_from_config", lambda _cfg: "ws://unit.test")
    monkeypatch.setattr("soothe_sdk.client.WebSocketClient", lambda url: stub_client)

    cfg = SimpleNamespace()
    exit_code = await daemon_exec.run_headless_via_daemon(cfg, prompt="hi")

    assert exit_code == 0
    processed_thread_ids = [e.get("thread_id") for e in _RecorderProcessor.events]
    assert all(tid in {None, active_thread_id} for tid in processed_thread_ids)
    assert leaked_text not in [str(e.get("data", "")) for e in _RecorderProcessor.events]
