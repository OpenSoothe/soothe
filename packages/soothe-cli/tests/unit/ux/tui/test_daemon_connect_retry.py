"""Tests for TUI daemon connect retry and attempt labels."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.app._startup import (
    _DAEMON_CONNECT_RETRY_DELAY_S,
    _DAEMON_READY_TIMEOUT_S,
    _StartupMixin,
)


class _ConnectProbe(_StartupMixin):
    """Minimal app stub for daemon connect tests."""

    class DaemonReady:
        def __init__(self, *, session: object, status_event: dict[str, object]) -> None:
            self.session = session
            self.status_event = status_event

    class ServerStartFailed:
        def __init__(self, *, error: BaseException) -> None:
            self.error = error

    def __init__(self) -> None:
        self._daemon_config = SimpleNamespace(daemon_host="127.0.0.1", daemon_port=8765)
        self._cwd = "/tmp/workspace"
        self._lc_loop_id: str | None = None
        self._set_spinner = AsyncMock()
        self.post_message = MagicMock()


def test_daemon_connect_hint_extra_omits_suffix_on_first_attempt() -> None:
    hint = _StartupMixin._daemon_connect_hint_extra(attempt=1, max_attempts=3)
    assert hint is None


def test_daemon_connect_hint_extra_includes_progress_after_retry() -> None:
    hint = _StartupMixin._daemon_connect_hint_extra(attempt=2, max_attempts=3)
    assert hint == "attempt 2/3"


def test_daemon_connect_hint_extra_omits_suffix_for_single_attempt() -> None:
    hint = _StartupMixin._daemon_connect_hint_extra(attempt=1, max_attempts=1)
    assert hint is None


@pytest.mark.asyncio
async def test_connect_daemon_background_retries_then_succeeds(monkeypatch) -> None:
    """Failed attempts should retry with visible attempt hints before success."""
    probe = _ConnectProbe()
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    attempts = {"count": 0}

    async def fake_connect_once(*, attempt: int) -> tuple[object, dict[str, object]]:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError(f"attempt {attempt} failed")
        return object(), {"loop_id": "loop-1", "type": "session_ready"}

    monkeypatch.setattr(probe, "_connect_daemon_once", fake_connect_once)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await probe._connect_daemon_background()

    assert attempts["count"] == 3
    assert sleep_calls == [_DAEMON_CONNECT_RETRY_DELAY_S, _DAEMON_CONNECT_RETRY_DELAY_S]
    probe.post_message.assert_called_once()
    assert probe.post_message.call_args.args[0].session is not None

    spinner_calls = probe._set_spinner.await_args_list
    assert spinner_calls[0].args[0] == "Waiting"
    assert spinner_calls[0].kwargs.get("hint_extra") is None
    assert spinner_calls[1].args[0] == "Waiting"
    assert spinner_calls[1].kwargs.get("hint_extra") == "attempt 2/3"
    assert spinner_calls[2].args[0] == "Waiting"
    assert spinner_calls[2].kwargs.get("hint_extra") == "attempt 3/3"


@pytest.mark.asyncio
async def test_connect_daemon_background_posts_failure_after_max_attempts(monkeypatch) -> None:
    probe = _ConnectProbe()

    async def always_fail(*, attempt: int) -> tuple[object, dict[str, object]]:
        raise ConnectionError(f"attempt {attempt} failed")

    monkeypatch.setattr(probe, "_connect_daemon_once", always_fail)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    await probe._connect_daemon_background()

    probe.post_message.assert_called_once()
    event = probe.post_message.call_args.args[0]
    assert "attempt 3 failed" in str(event.error)


@pytest.mark.asyncio
async def test_connect_daemon_once_uses_extended_ready_timeout(monkeypatch) -> None:
    probe = _ConnectProbe()
    captured: dict[str, float] = {}

    async def fake_is_daemon_live(
        ws_url: str,
        *,
        timeout: float,
        wait_for_ready: bool,
        ready_timeout: float,
    ) -> bool:
        captured["ws_url"] = ws_url
        captured["timeout"] = timeout
        captured["wait_for_ready"] = wait_for_ready
        captured["ready_timeout"] = ready_timeout
        return True

    class FakeSession:
        async def connect(self, *, resume_loop_id: str | None) -> dict[str, str]:
            return {"loop_id": "loop-abc", "type": "session_ready"}

    monkeypatch.setattr(
        "soothe_client.is_daemon_live",
        fake_is_daemon_live,
    )
    monkeypatch.setattr(
        "soothe_cli.runtime.transport.session.TuiDaemonSession",
        lambda *args, **kwargs: FakeSession(),
    )

    session, status = await probe._connect_daemon_once(attempt=1)

    assert captured["ready_timeout"] == _DAEMON_READY_TIMEOUT_S
    assert captured["wait_for_ready"] is True
    assert status["loop_id"] == "loop-abc"
    assert session is not None

    connecting_calls = [
        call
        for call in probe._set_spinner.await_args_list
        if call.args and call.args[0] == "Connecting"
    ]
    assert connecting_calls == [connecting_calls[0]]
    assert connecting_calls[0].kwargs.get("hint_extra") is None
