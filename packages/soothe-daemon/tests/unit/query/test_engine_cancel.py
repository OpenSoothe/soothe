"""Regression tests for daemon query cancellation behavior."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.query import QueryEngine
from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget


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


class _ChunkedRunner:
    """Yields a fixed number of stream chunks with a delay between each."""

    def __init__(self, *, chunk_count: int, chunk_delay: float) -> None:
        self.current_thread_id = "thread-1"
        self.chunk_count = chunk_count
        self.chunk_delay = chunk_delay
        self.chunks_yielded = 0

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None

    async def create_persisted_thread(self, thread_id: str | None = None) -> Any:
        del thread_id
        return SimpleNamespace(thread_id="thread-1")

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[override]
        for _ in range(self.chunk_count):
            await asyncio.sleep(self.chunk_delay)
            self.chunks_yielded += 1
            yield ("", "messages", ())


class _PerLoopRunnerFactory:
    """Create independent chunked runners per loop id."""

    def __init__(self, *, chunk_count: int, chunk_delay: float) -> None:
        self._chunk_count = chunk_count
        self._chunk_delay = chunk_delay
        self.runners: dict[str, _ChunkedRunner] = {}

    def create_runner(self, loop_id: str) -> _FakeLoopRunner:
        runner = _ChunkedRunner(
            chunk_count=self._chunk_count,
            chunk_delay=self._chunk_delay,
        )
        self.runners[loop_id] = runner
        return _FakeLoopRunner(runner)


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


class _FakePersistenceManager:
    async def get_loop_metadata(self, _loop_id: str) -> dict[str, Any] | None:
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
            log=lambda *_args, **_kwargs: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    output_streaming=SimpleNamespace(
                        adaptive_threshold_chars=500,
                        adaptive_block_chars=1024,
                        adaptive_block_interval_ms=250,
                        file_output_threshold_chars=0,
                        file_output_preview_chars=500,
                        file_output_dir=None,
                        streaming_interval_ms=300,
                        message_coalesce_enabled=True,
                        tool_batch_enabled=True,
                        tool_batch_interval_ms=200,
                        suppress_redundant_stream_tool_updates=True,
                        skip_redundant_tool_message_wire=False,
                    )
                )
            ),
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _current_query_task=None,
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _loop_broadcast_budget=LoopBroadcastBudget(80),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
            get_stream_delivery=lambda *_args, **_kwargs: "batch",
            await_loop_delivery_drained=AsyncMock(return_value=True),
            get_clients_for_loop=AsyncMock(return_value=[]),  # RFC-450 §9.4
            get_loop_subscription_id=AsyncMock(return_value=None),  # RFC-450 §9.4
        ),
        _message_router=SimpleNamespace(
            _send_complete=lambda *_args, **_kwargs: None,  # RFC-450 §9.4
        ),
        _persistence_manager=_FakePersistenceManager(),
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
            log=lambda *_args, **_kwargs: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    output_streaming=SimpleNamespace(
                        adaptive_threshold_chars=500,
                        adaptive_block_chars=1024,
                        adaptive_block_interval_ms=250,
                        file_output_threshold_chars=0,
                        file_output_preview_chars=500,
                        file_output_dir=None,
                        streaming_interval_ms=300,
                        message_coalesce_enabled=True,
                        tool_batch_enabled=True,
                        tool_batch_interval_ms=200,
                        suppress_redundant_stream_tool_updates=True,
                        skip_redundant_tool_message_wire=False,
                    )
                )
            ),
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _current_query_task=None,
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _loop_broadcast_budget=LoopBroadcastBudget(80),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
            get_stream_delivery=lambda *_args, **_kwargs: "batch",
            await_loop_delivery_drained=AsyncMock(return_value=True),
            get_clients_for_loop=AsyncMock(return_value=[]),  # RFC-450 §9.4
            get_loop_subscription_id=AsyncMock(return_value=None),  # RFC-450 §9.4
        ),
        _message_router=SimpleNamespace(
            _send_complete=lambda *_args, **_kwargs: None,  # RFC-450 §9.4
        ),
        _persistence_manager=_FakePersistenceManager(),
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
    # Use min allowed grace (1s) with slightly longer unwind (1.1s)
    # This tests the "grace timeout while unwinding" path in ~1.3s total.
    runner = _SlowCancelRunner(unwind_delay=1.1)
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

    # Wait for unwind to complete (1.1s unwind - 1s grace timeout already elapsed + margin)
    await asyncio.sleep(0.2)
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
            log=lambda *_args, **_kwargs: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    output_streaming=SimpleNamespace(
                        adaptive_threshold_chars=500,
                        adaptive_block_chars=1024,
                        adaptive_block_interval_ms=250,
                        file_output_threshold_chars=0,
                        file_output_preview_chars=500,
                        file_output_dir=None,
                        streaming_interval_ms=300,
                        message_coalesce_enabled=True,
                        tool_batch_enabled=True,
                        tool_batch_interval_ms=200,
                        suppress_redundant_stream_tool_updates=True,
                        skip_redundant_tool_message_wire=False,
                    )
                )
            ),
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _current_query_task=None,
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _loop_broadcast_budget=LoopBroadcastBudget(80),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
            get_stream_delivery=lambda *_args, **_kwargs: "batch",
            await_loop_delivery_drained=AsyncMock(return_value=True),
            get_clients_for_loop=AsyncMock(return_value=[]),  # RFC-450 §9.4
            get_loop_subscription_id=AsyncMock(return_value=None),  # RFC-450 §9.4
        ),
        _message_router=SimpleNamespace(
            _send_complete=lambda *_args, **_kwargs: None,  # RFC-450 §9.4
        ),
        _persistence_manager=_FakePersistenceManager(),
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


@pytest.mark.asyncio
async def test_concurrent_query_does_not_abort_unrelated_stream() -> None:
    """A later query replacing ``_current_query_task`` must not stop an earlier stream."""
    broadcasts: list[dict[str, Any]] = []
    slow_factory = _PerLoopRunnerFactory(chunk_count=6, chunk_delay=0.04)
    fast_factory = _PerLoopRunnerFactory(chunk_count=1, chunk_delay=0.0)

    daemon = _daemon_factory(
        runner=_ChunkedRunner(chunk_count=1, chunk_delay=0.0),
        broadcasts=broadcasts,
    )
    daemon._runner_factory = slow_factory

    engine = QueryEngine(daemon)
    await engine.run_query("slow loop", loop_id="loop-slow")
    slow_task = daemon._current_query_task
    assert slow_task is not None

    await asyncio.sleep(0.05)
    assert slow_factory.runners["loop-slow"].chunks_yielded >= 1

    daemon._runner_factory = fast_factory
    await engine.run_query("fast loop", loop_id="loop-fast")
    fast_task = daemon._current_query_task
    assert fast_task is not None
    assert fast_task is not slow_task

    await asyncio.sleep(0.05)
    await fast_task
    assert fast_factory.runners["loop-fast"].chunks_yielded == 1
    assert not slow_task.done()

    await slow_task
    assert slow_factory.runners["loop-slow"].chunks_yielded == 6


@pytest.mark.asyncio
async def test_cancel_loop_without_active_task_records_pending_cancel() -> None:
    """Idle cancel must arm ``_pending_cancels`` for the pre-registration race window."""
    broadcasts: list[dict[str, Any]] = []
    runner = _ChunkedRunner(chunk_count=3, chunk_delay=0.02)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts)
    engine = QueryEngine(daemon)

    engine.mark_loop_turn_starting("loop-a")
    await engine.cancel_loop("loop-a")

    assert "loop-a" in engine._pending_cancels


@pytest.mark.asyncio
async def test_idle_cancel_does_not_arm_pending_cancel() -> None:
    """``/cancel`` on an idle loop must not poison the next submit."""
    broadcasts: list[dict[str, Any]] = []
    runner = _ChunkedRunner(chunk_count=3, chunk_delay=0.02)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts)
    daemon._thread_registry = _RegistryMapsThreadLoop({"thread-1": "loop-a"})
    engine = QueryEngine(daemon)

    await engine.cancel_loop("loop-a")

    assert "loop-a" not in engine._pending_cancels
    assert not any(m.get("type") == "command_response" for m in broadcasts)

    await engine.run_query("after idle cancel", loop_id="loop-a")
    await asyncio.sleep(0.15)
    assert runner.chunks_yielded >= 1


@pytest.mark.asyncio
async def test_duplicate_cancel_does_not_poison_immediate_resubmit() -> None:
    """Multiple ``/cancel`` during Ctrl+C must not leave a stale ``_pending_cancels`` token."""
    broadcasts: list[dict[str, Any]] = []
    runner = _ChunkedRunner(chunk_count=20, chunk_delay=0.03)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=60)
    daemon._thread_registry = _RegistryMapsThreadLoop({"thread-1": "loop-a"})
    engine = QueryEngine(daemon)

    await engine.run_query("first", loop_id="loop-a")
    await asyncio.sleep(0.05)
    assert runner.chunks_yielded >= 1
    task1 = daemon._current_query_task
    assert task1 is not None

    await engine.cancel_loop("loop-a")
    await engine.cancel_loop("loop-a")
    await engine.cancel_loop("loop-a")
    assert "loop-a" not in engine._pending_cancels

    with suppress(asyncio.CancelledError):
        await task1

    runner.chunks_yielded = 0
    await engine.run_query("second", loop_id="loop-a")
    await asyncio.sleep(0.2)

    assert runner.chunks_yielded >= 1, "resubmit should stream, not hit cancelled_before_start"


@pytest.mark.asyncio
async def test_pending_cancel_aborts_query_before_stream_starts() -> None:
    """A pending cancel recorded before task registration must abort ``_run_stream``."""
    broadcasts: list[dict[str, Any]] = []
    runner = _ChunkedRunner(chunk_count=5, chunk_delay=0.03)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts)
    daemon._thread_registry = _RegistryMapsThreadLoop({"thread-1": "loop-a"})
    engine = QueryEngine(daemon)

    engine._pending_cancels.add("loop-a")
    await engine.run_query("hello", loop_id="loop-a")
    await asyncio.sleep(0.15)

    assert runner.chunks_yielded == 0
    assert "loop-a" not in engine._pending_cancels
    idle_msgs = [
        m
        for m in broadcasts
        if m.get("type") == "status" and m.get("state") == "idle" and m.get("loop_id") == "loop-a"
    ]
    assert idle_msgs


@pytest.mark.asyncio
async def test_cancel_running_query_does_not_poison_immediate_resubmit() -> None:
    """Ctrl+C on a running query must not leave a stale ``_pending_cancels`` token."""
    broadcasts: list[dict[str, Any]] = []
    runner = _ChunkedRunner(chunk_count=5, chunk_delay=0.03)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts, cancel_grace_seconds=60)
    daemon._thread_registry = _RegistryMapsThreadLoop({"thread-1": "loop-a"})
    engine = QueryEngine(daemon)

    await engine.run_query("first", loop_id="loop-a")
    await asyncio.sleep(0.05)
    assert runner.chunks_yielded >= 1
    task1 = daemon._current_query_task
    assert task1 is not None

    await engine.cancel_loop("loop-a")
    assert "loop-a" not in engine._pending_cancels

    with suppress(asyncio.CancelledError):
        await task1

    runner.chunks_yielded = 0
    await engine.run_query("second", loop_id="loop-a")
    await asyncio.sleep(0.2)

    assert runner.chunks_yielded >= 1, "resubmit should stream, not hit cancelled_before_start"
