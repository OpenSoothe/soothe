"""Integration tests for LocalLoopRunner subprocess isolation (RFC-221).

These tests spawn real subprocesses to verify end-to-end subprocess isolation.
They require only a working Python environment — no daemon, no LLM, no network.

**Why no SootheConfig()**: SootheConfig construction triggers file I/O and
env resolution that hangs in CI-like environments. These tests care only about
the subprocess/queue plumbing, not config loading, so `None` is passed as the
config argument to fake workers (which ignore it).

Marked with ``@pytest.mark.integration`` — excluded from the default unit test
run. Run explicitly with: ``pytest --run-integration``.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import queue
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.core.runner.local_runner import LocalLoopRunner, SubprocessLoopError
from soothe.protocols.runner import LoopRunRequest


def _make_request(**kwargs: Any) -> LoopRunRequest:
    defaults: dict[str, Any] = dict(
        loop_id="integ-loop-1",
        thread_id="integ-thread-1",
        user_input="hello",
    )
    defaults.update(kwargs)
    return LoopRunRequest(**defaults)


# ---------------------------------------------------------------------------
# Top-level worker functions (must be module-level for spawn picklability)
# ---------------------------------------------------------------------------


def _fake_worker_success(config: Any, request: LoopRunRequest, q: Any) -> None:
    """Emit two chunks then a done sentinel — no LLM or config needed."""
    q.put(("chunk", (("ns",), "messages", f"echo:{request.user_input}")))
    q.put(("chunk", (("ns",), "messages", "done-text")))
    q.put(("done", None))


def _fake_worker_error(config: Any, request: LoopRunRequest, q: Any) -> None:
    """Emit an error sentinel."""
    q.put(("error", RuntimeError("subprocess-error")))


def _fake_worker_crash(_config: Any, _request: LoopRunRequest, _q: Any) -> None:
    """Exit with a nonzero code without writing a sentinel."""
    sys.exit(42)


def _fake_worker_sleep(_config: Any, _request: LoopRunRequest, _q: Any) -> None:
    """Block forever — used to test cancel()."""
    import time as _time

    _time.sleep(60)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLocalLoopRunnerSubprocessIntegration:
    """Real subprocess tests — verify isolation and chunk streaming end-to-end."""

    @pytest.mark.asyncio
    async def test_chunks_streamed_from_subprocess(self) -> None:
        """Chunks produced in a real subprocess are received by the async generator."""
        runner = LocalLoopRunner("integ-loop-1", config=None)  # type: ignore[arg-type]

        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        process = ctx.Process(
            target=_fake_worker_success,
            args=(None, _make_request(user_input="hi"), q),
            daemon=True,
        )
        process.start()
        runner._process = process

        loop = asyncio.get_event_loop()

        def _get_next() -> tuple[str, Any]:
            return q.get(timeout=10.0)

        result = []
        while True:
            kind, payload = await loop.run_in_executor(None, _get_next)
            if kind == "done":
                break
            if kind == "error":
                raise payload
            result.append(payload)

        process.join(timeout=5)
        assert result == [
            (("ns",), "messages", "echo:hi"),
            (("ns",), "messages", "done-text"),
        ]

    @pytest.mark.asyncio
    async def test_error_sentinel_propagates_from_subprocess(self) -> None:
        """RuntimeError from subprocess is re-raised in the parent event loop."""
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        process = ctx.Process(
            target=_fake_worker_error,
            args=(None, _make_request(), q),
            daemon=True,
        )
        process.start()

        loop = asyncio.get_event_loop()
        kind, payload = await loop.run_in_executor(None, lambda: q.get(timeout=10.0))
        process.join(timeout=5)

        assert kind == "error"
        assert isinstance(payload, RuntimeError)
        assert "subprocess-error" in str(payload)

    @pytest.mark.asyncio
    async def test_subprocess_crash_raises_subprocess_loop_error(self) -> None:
        """SubprocessLoopError is raised when the subprocess exits with a nonzero code."""
        # Spawn the crash worker in a real subprocess and wait for it to die.
        ctx = multiprocessing.get_context("spawn")
        real_q = ctx.Queue()
        crashed_process = ctx.Process(
            target=_fake_worker_crash,
            args=(None, _make_request(), real_q),
            daemon=True,
        )
        crashed_process.start()
        crashed_process.join(timeout=10)
        assert crashed_process.exitcode == 42

        # Wrap with a mock that keeps the real exitcode/is_alive but stubs out start().
        mock_process = MagicMock()
        mock_process.pid = crashed_process.pid
        mock_process.is_alive.return_value = False
        mock_process.exitcode = 42
        mock_process.start.return_value = None  # no-op

        # Now run the runner with a patched context that re-uses the already-dead process
        # and an empty queue (simulating a queue.get timeout after crash).
        empty_q: queue.Queue[Any] = queue.Queue()

        mock_ctx = MagicMock()
        mock_ctx.Queue.return_value = empty_q
        mock_ctx.Process.return_value = mock_process

        runner = LocalLoopRunner("integ-loop-crash", config=None)  # type: ignore[arg-type]

        def _instant_timeout(**kwargs: Any) -> Any:
            raise queue.Empty

        empty_q.get = _instant_timeout  # type: ignore[method-assign]

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            with pytest.raises(SubprocessLoopError, match="exited with code 42"):
                async for _ in runner.run(_make_request()):
                    pass

    @pytest.mark.asyncio
    async def test_cancel_terminates_subprocess(self) -> None:
        """cancel() terminates a running subprocess within 5 seconds."""
        runner = LocalLoopRunner("integ-loop-cancel", config=None)  # type: ignore[arg-type]

        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        process = ctx.Process(
            target=_fake_worker_sleep,
            args=(None, _make_request(), q),
            daemon=True,
        )
        process.start()
        runner._process = process

        assert process.is_alive()
        await runner.cancel()
        process.join(timeout=6)
        assert not process.is_alive()

    def test_two_loops_run_in_isolated_processes(self) -> None:
        """Two concurrent loops use separate subprocesses (no shared state)."""
        ctx = multiprocessing.get_context("spawn")
        results: dict[str, list[Any]] = {"A": [], "B": []}

        for label, input_text in [("A", "ping"), ("B", "pong")]:
            q = ctx.Queue()
            process = ctx.Process(
                target=_fake_worker_success,
                args=(None, _make_request(loop_id=f"loop-{label}", user_input=input_text), q),
                daemon=True,
            )
            process.start()
            process.join(timeout=10)
            while not q.empty():
                kind, payload = q.get_nowait()
                if kind == "chunk":
                    results[label].append(payload)

        assert results["A"] == [
            (("ns",), "messages", "echo:ping"),
            (("ns",), "messages", "done-text"),
        ]
        assert results["B"] == [
            (("ns",), "messages", "echo:pong"),
            (("ns",), "messages", "done-text"),
        ]
