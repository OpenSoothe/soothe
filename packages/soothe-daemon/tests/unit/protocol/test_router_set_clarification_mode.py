"""Tests for the `loop_set_clarification_mode` router handler.

Covers the interaction_mode extension: bypass is accepted and forwarded to
the runner; plan/ask are rejected (they apply on the next turn, not as a
hot-swap); a missing active runner returns `{"applied": False}`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.protocol import MessageRouter


class _FakeDaemon:
    _session_manager = SimpleNamespace()

    def __init__(self, *, query_engine: Any = None) -> None:
        self.sent: list[tuple[Any, dict[str, Any]]] = []
        self._query_engine = query_engine

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        self.sent.append((client_id, msg))


def _make_router(daemon: _FakeDaemon) -> MessageRouter:
    router = MessageRouter(daemon)
    router._is_handshake_complete = lambda _cid: True  # type: ignore[method-assign]
    return router


class _FakeRunner:
    """Async runner stub recording `set_clarification_mode` calls."""

    def __init__(self, *, applied: bool = True) -> None:
        self.applied = applied
        self.calls: list[tuple[str, str | None]] = []

    async def set_clarification_mode(
        self,
        mode: str,
        *,
        interaction_mode: str | None = None,
    ) -> bool:
        self.calls.append((mode, interaction_mode))
        return self.applied


def _daemon_with_runner(runner: _FakeRunner) -> _FakeDaemon:
    qe = SimpleNamespace(_active_runners={"loop-1": SimpleNamespace(runner=runner)})
    return _FakeDaemon(query_engine=qe)


@pytest.mark.asyncio
async def test_bypass_interaction_mode_forwarded() -> None:
    runner = _FakeRunner(applied=True)
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r1", "loop_id": "loop-1", "mode": "auto", "interaction_mode": "bypass"},
    )

    assert runner.calls == [("auto", "bypass")]
    assert len(router._daemon.sent) == 1
    _cid, env = router._daemon.sent[0]
    assert env["type"] == "response"
    assert env["result"] == {"applied": True}


@pytest.mark.asyncio
async def test_omitted_interaction_mode_defaults_to_none() -> None:
    runner = _FakeRunner(applied=True)
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r2", "loop_id": "loop-1", "mode": "manual"},
    )

    assert runner.calls == [("manual", None)]


@pytest.mark.asyncio
async def test_plan_interaction_mode_rejected() -> None:
    """plan is a standalone working mode — not a live hot-swap target."""
    runner = _FakeRunner()
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r3", "loop_id": "loop-1", "mode": "auto", "interaction_mode": "plan"},
    )

    assert runner.calls == []
    assert len(router._daemon.sent) == 1
    _cid, env = router._daemon.sent[0]
    assert env["type"] == "error"
    assert env["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
async def test_ask_interaction_mode_rejected() -> None:
    runner = _FakeRunner()
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r4", "loop_id": "loop-1", "mode": "auto", "interaction_mode": "ask"},
    )

    assert runner.calls == []
    _cid, env = router._daemon.sent[0]
    assert env["type"] == "error"


@pytest.mark.asyncio
async def test_invalid_clarification_mode_rejected() -> None:
    runner = _FakeRunner()
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r5", "loop_id": "loop-1", "mode": "bogus"},
    )

    assert runner.calls == []
    _cid, env = router._daemon.sent[0]
    assert env["type"] == "error"


@pytest.mark.asyncio
async def test_no_active_runner_returns_applied_false() -> None:
    daemon = _FakeDaemon(query_engine=SimpleNamespace(_active_runners={}))
    router = _make_router(daemon)

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r6", "loop_id": "loop-1", "mode": "auto"},
    )

    _cid, env = daemon.sent[0]
    assert env["type"] == "response"
    assert env["result"] == {"applied": False}


@pytest.mark.asyncio
async def test_runner_exception_returns_applied_false() -> None:
    runner = _FakeRunner()
    runner.set_clarification_mode = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r7", "loop_id": "loop-1", "mode": "auto", "interaction_mode": "bypass"},
    )

    _cid, env = router._daemon.sent[0]
    assert env["type"] == "response"
    assert env["result"] == {"applied": False}


@pytest.mark.asyncio
async def test_missing_loop_id_is_invalid_request() -> None:
    runner = _FakeRunner()
    router = _make_router(_daemon_with_runner(runner))

    await router._handle_loop_set_clarification_mode(
        "client-1",
        {"request_id": "r8", "mode": "auto"},
    )

    assert runner.calls == []
    _cid, env = router._daemon.sent[0]
    assert env["type"] == "error"
    assert env["error"]["code"] == -32600  # INVALID_REQUEST
