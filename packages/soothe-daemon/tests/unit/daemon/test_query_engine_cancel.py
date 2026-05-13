"""Regression tests for daemon query cancellation behavior."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.query_engine import QueryEngine


class _FakeRunner:
    def __init__(self) -> None:
        self.current_thread_id = "thread-1"

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None

    async def create_persisted_thread(self, thread_id: str | None = None) -> Any:
        del thread_id
        return SimpleNamespace(thread_id="thread-1")

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    def set_interrupt_resolver(self, loop_id: str, _resolver: Any) -> None:
        del loop_id
        return None

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[override]
        # Brief sleep so run_query's asyncio.sleep(0) yield does not return after the
        # stream has already completed (would leave _current_query_task cleared).
        await asyncio.sleep(0.05)
        raise asyncio.CancelledError
        yield  # pragma: no cover


class _FakeLoopRunner:
    """Wraps a fake runner to satisfy ``LoopRunnerProtocol``."""

    def __init__(self, runner: _FakeRunner | _SlowCancelRunner) -> None:
        self._runner = runner
        self._cancelled = False

    async def run(self, _request: Any) -> Any:  # type: ignore[no-untyped-def]  # noqa: ANN401
        async for chunk in self._runner.astream(""):
            yield chunk

    async def cancel(self) -> None:
        self._cancelled = True


class _FakeRunnerFactory:
    """Creates ``_FakeLoopRunner`` instances backed by a shared runner."""

    def __init__(self, runner: _FakeRunner | _SlowCancelRunner) -> None:
        self._runner = runner

    def create_runner(self, loop_id: str) -> _FakeLoopRunner:  # noqa: ARG002
        return _FakeLoopRunner(self._runner)


class _SlowCancelRunner(_FakeRunner):
    """Simulates subagent unwind: cancellation delivers after a delay (IG-398)."""

    def __init__(self, unwind_delay: float = 0.05) -> None:
        super().__init__()
        self.unwind_delay = unwind_delay

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[override]
        try:
            await asyncio.sleep(10000.0)
            yield ("", "messages", ())  # pragma: no cover
        except asyncio.CancelledError:
            await asyncio.sleep(self.unwind_delay)
            raise


class _FakeThreadRegistry:
    def get(self, _thread_id: str) -> None:
        return None

    def get_thread_loop(self, _thread_id: str) -> str:
        return ""

    def get_workspace(self, _thread_id: str) -> Path:
        return Path.cwd()

    def ensure(self, _thread_id: str, *, is_draft: bool = False) -> None:
        del is_draft

    def set_workspace(self, _thread_id: str, _workspace: Path) -> None:
        return None


@pytest.mark.asyncio
async def test_cancelled_query_does_not_emit_custom_error_event() -> None:
    """Cancelled turns should only update status, not emit stale cancel error events."""
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    runner = _FakeRunner()
    daemon_config = SootheDaemonConfig()
    daemon = SimpleNamespace(
        _runner=runner,
        _runner_factory=_FakeRunnerFactory(runner),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _query_running=False,
        _current_query_task=None,
        _pending_interrupt_responses={},
        _active_stream_loop_ids=set(),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
        ),
    )

    engine = QueryEngine(daemon)
    await engine.run_query("cancel me", loop_id="loop-cancel")

    task = daemon._current_query_task
    assert task is not None
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    custom_errors = [
        msg
        for msg in broadcasts
        if msg.get("type") == "event"
        and msg.get("mode") == "custom"
        and isinstance(msg.get("data"), dict)
        and str(msg["data"].get("error", "")).startswith("Query cancelled")
    ]
    assert custom_errors == []


def _daemon_factory(
    *,
    runner: Any,
    broadcasts: list[dict[str, Any]],
    cancel_grace_seconds: int = 30,
) -> SimpleNamespace:
    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    daemon_config = SootheDaemonConfig(
        max_query_duration_minutes=0,
        max_concurrent_threads=100,
        cancel_grace_seconds=cancel_grace_seconds,
    )

    return SimpleNamespace(
        _runner=runner,
        _runner_factory=_FakeRunnerFactory(runner),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _query_running=False,
        _current_query_task=None,
        _pending_interrupt_responses={},
        _active_stream_loop_ids=set(),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
        ),
    )


@pytest.mark.asyncio
async def test_cancel_does_not_emit_legacy_success_or_early_idle() -> None:
    """cancel_current_query must not broadcast legacy success or forge idle (IG-398)."""
    broadcasts: list[dict[str, Any]] = []
    runner = _SlowCancelRunner(unwind_delay=0.02)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=60)
    engine = QueryEngine(daemon)

    await engine.run_query("hello", loop_id="loop-cancel")
    task = daemon._current_query_task
    assert task is not None

    await engine.cancel_current_query()

    contents = [
        str(m.get("content", "")) for m in broadcasts if m.get("type") == "command_response"
    ]
    assert any("Cancellation requested" in c for c in contents)
    assert not any("Query cancelled successfully" in c for c in contents)

    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_waits_for_slow_unwind_before_idle() -> None:
    """Idle status must come from _run_stream finally, after cancel unwind completes."""
    broadcasts: list[dict[str, Any]] = []
    runner = _SlowCancelRunner(unwind_delay=0.06)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=60)
    engine = QueryEngine(daemon)

    await engine.run_query("slow cancel", loop_id="loop-cancel")
    await engine.cancel_current_query()

    idle_after_cancel = [
        i
        for i, m in enumerate(broadcasts)
        if m.get("type") == "status"
        and m.get("state") == "idle"
        and m.get("loop_id") == "loop-cancel"
    ]
    cmd_ix = next(
        i
        for i, m in enumerate(broadcasts)
        if m.get("type") == "command_response"
        and "Cancellation requested" in str(m.get("content", ""))
    )
    assert idle_after_cancel, "expected idle from stream finally"
    assert min(idle_after_cancel) > cmd_ix, "idle must not precede cancel acknowledgement"


@pytest.mark.asyncio
async def test_cancel_grace_timeout_keeps_task_then_drains(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Grace shorter than unwind: cancel returns while unwinding; task kept until finally."""
    broadcasts: list[dict[str, Any]] = []
    # Unwind longer than cancel_grace_seconds (min 1s per DaemonConfig) triggers warning path.
    runner = _SlowCancelRunner(unwind_delay=2.0)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=1)
    engine = QueryEngine(daemon)

    await engine.run_query("blocking unwind", loop_id="loop-cancel")
    task = daemon._current_query_task
    assert task is not None

    caplog.set_level(logging.WARNING, logger="soothe_daemon.query_engine")

    await engine.cancel_current_query()

    warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("still unwinding" in m for m in warn_msgs)

    assert daemon._current_query_task is task
    assert not task.done()

    await asyncio.sleep(2.5)
    with suppress(asyncio.CancelledError):
        await task
    assert task.done()


@pytest.mark.asyncio
async def test_cancel_loop_noop_when_loop_id_empty() -> None:
    """Empty loop_id must not cancel threads or match unscoped registry entries."""
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    runner = _SlowCancelRunner(unwind_delay=0.04)
    daemon_config = SootheDaemonConfig(
        max_query_duration_minutes=0,
        max_concurrent_threads=100,
        cancel_grace_seconds=60,
    )
    daemon = SimpleNamespace(
        _runner=runner,
        _runner_factory=_FakeRunnerFactory(runner),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _query_running=False,
        _current_query_task=None,
        _pending_interrupt_responses={},
        _active_stream_loop_ids=set(),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
        ),
    )

    engine = QueryEngine(daemon)
    await engine.run_query("hello", loop_id="loop-cancel")
    task = daemon._current_query_task
    assert task is not None
    assert not task.done()

    await engine.cancel_loop("")
    assert not task.done()
    assert not any(m.get("type") == "command_response" for m in broadcasts)

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class _RegistryMapsThreadLoop(_FakeThreadRegistry):
    """Maps checkpoint thread ids to client loop ids for ``cancel_loop`` task lookup."""

    def __init__(self, thread_to_loop: dict[str, str]) -> None:
        self._thread_to_loop = thread_to_loop

    def get_thread_loop(self, thread_id: str) -> str:
        return self._thread_to_loop.get(thread_id, "")


@pytest.mark.asyncio
async def test_cancel_loop_cancels_subprocess_runner_before_stream_finally() -> None:
    """``cancel_loop`` must call ``LoopRunner.cancel`` while the runner is still active."""
    broadcasts: list[dict[str, Any]] = []
    runner = _SlowCancelRunner(unwind_delay=0.02)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=60)
    daemon._thread_registry = _RegistryMapsThreadLoop({"thread-1": "loop-a"})

    engine = QueryEngine(daemon)
    await engine.run_query("hello", loop_id="loop-a")
    await asyncio.sleep(0.05)
    assert "loop-a" in engine._active_runners
    loop_runner = engine._active_runners["loop-a"]
    assert loop_runner._cancelled is False

    task = daemon._current_query_task
    assert task is not None

    await engine.cancel_loop("loop-a")

    assert loop_runner._cancelled is True
    assert "loop-a" not in engine._active_runners
    assert any(
        m.get("type") == "command_response"
        and m.get("loop_id") == "loop-a"
        and "Cancellation requested" in str(m.get("content", ""))
        for m in broadcasts
    )

    with suppress(asyncio.CancelledError):
        await task
