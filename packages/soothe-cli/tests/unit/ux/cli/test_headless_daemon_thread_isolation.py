"""Regression tests for headless daemon loop isolation."""

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


class _StubSession:
    """DaemonSession stub wrapping an event-playing client."""

    def __init__(self, client: _StubClient, loop_id: str) -> None:
        self._client = client
        self._loop_id = loop_id

    @property
    def client(self) -> _StubClient:
        return self._client

    @property
    def loop_id(self) -> str:
        return self._loop_id

    async def connect(self, *, resume_loop_id: str | None = None) -> dict[str, Any]:
        del resume_loop_id
        return {"type": "session_ready", "loop_id": self._loop_id, "success": True}

    async def send_turn(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def cancel_remote_query(self) -> None:
        return None

    async def close(self, **_kwargs: Any) -> None:
        await self._client.close()


class _RecorderProcessor:
    """EventProcessor stub that records processed frames."""

    events: list[dict[str, Any]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.events = []
        _RecorderProcessor.events = self.events

    def process_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_run_headless_filters_non_active_loop_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    """Headless daemon run should ignore `status/event` frames for other loops."""
    active_loop_id = "loop-main"
    leaked_text = (
        "Hello! I'd be happy to help you with whatever you need. What can I do for you today?"
    )

    stub_client = _StubClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-other"},
            {
                "type": "event",
                "loop_id": "loop-other",
                "mode": "messages",
                "namespace": [],
                "data": leaked_text,
            },
            {"type": "status", "state": "running", "loop_id": active_loop_id},
            {"type": "event", "loop_id": active_loop_id, "mode": "custom", "data": {"type": "ok"}},
            {"type": "status", "state": "idle", "loop_id": active_loop_id},
            {"type": "event", "loop_id": "loop-other", "mode": "custom", "data": {"type": "late"}},
            None,
        ]
    )

    def _session_factory(*_args: Any, **_kwargs: Any) -> _StubSession:
        return _StubSession(stub_client, active_loop_id)

    monkeypatch.setattr(daemon_exec, "EventProcessor", _RecorderProcessor)
    monkeypatch.setattr(daemon_exec, "websocket_url_from_config", lambda _cfg: "ws://unit.test")
    monkeypatch.setattr(daemon_exec, "DaemonSession", _session_factory)

    cfg = SimpleNamespace()
    exit_code = await daemon_exec.run_headless_via_daemon(cfg, prompt="hi")

    assert exit_code == 0
    processed_loop_ids = [e.get("loop_id") for e in _RecorderProcessor.events]
    assert all(lid in {None, active_loop_id} for lid in processed_loop_ids)
    assert leaked_text not in [str(e.get("data", "")) for e in _RecorderProcessor.events]
