"""Unit tests for LocalLoopRunner (RFC-221).

Mocks multiprocessing.Process and Queue so no real subprocess is spawned.
"""

from __future__ import annotations

import pickle
import queue
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.runner.local_runner import LocalLoopRunner, SubprocessLoopError
from soothe.protocols.runner import LoopRunRequest


def _make_request(**kwargs: Any) -> LoopRunRequest:
    defaults: dict[str, Any] = dict(
        loop_id="loop-1",
        thread_id="thread-1",
        user_input="hello",
    )
    defaults.update(kwargs)
    return LoopRunRequest(**defaults)


def _make_config() -> SootheConfig:
    return SootheConfig()


class TestLocalLoopRunnerRun:
    """run() drains queue items and yields chunk payloads."""

    @pytest.mark.asyncio
    async def test_yields_chunks_then_done(self) -> None:
        """Chunks are yielded in order; done sentinel stops iteration."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        chunk1 = (("ns",), "messages", "hello")
        chunk2 = (("ns",), "messages", "world")

        # Build a synchronous queue pre-filled with items
        q: queue.Queue[tuple[str, Any]] = queue.Queue()
        q.put(("chunk", chunk1))
        q.put(("chunk", chunk2))
        q.put(("done", None))

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        ctx = MagicMock()
        ctx.Queue.return_value = q
        ctx.Process.return_value = mock_process

        with patch("multiprocessing.get_context", return_value=ctx):
            result = []
            async for chunk in runner.run(_make_request()):
                result.append(chunk)

        assert result == [chunk1, chunk2]

    @pytest.mark.asyncio
    async def test_spawn_args_picklable_with_polluted_config_cache(self) -> None:
        """Runtime model cache must not be sent to the child; spawn uses JSON copy."""
        config = _make_config()
        config._model_cache["x"] = threading.RLock()  # type: ignore[attr-defined]
        runner = LocalLoopRunner("loop-1", config)

        q: queue.Queue[tuple[str, Any]] = queue.Queue()
        q.put(("done", None))
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True
        ctx = MagicMock()
        ctx.Queue.return_value = q
        ctx.Process.return_value = mock_process

        with patch("multiprocessing.get_context", return_value=ctx):
            async for _ in runner.run(_make_request()):
                pass

        args = ctx.Process.call_args[1]["args"]
        pickle.dumps(args[0])
        pickle.dumps(args[1])

    @pytest.mark.asyncio
    async def test_raises_on_error_sentinel(self) -> None:
        """error sentinel re-raises the exception from the subprocess."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        exc = ValueError("boom")
        q: queue.Queue[tuple[str, Any]] = queue.Queue()
        q.put(("error", exc))

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        ctx = MagicMock()
        ctx.Queue.return_value = q
        ctx.Process.return_value = mock_process

        with patch("multiprocessing.get_context", return_value=ctx):
            with pytest.raises(ValueError, match="boom"):
                async for _ in runner.run(_make_request()):
                    pass

    @pytest.mark.asyncio
    async def test_raises_subprocess_loop_error_on_nonzero_exit(self) -> None:
        """SubprocessLoopError raised when process exits with nonzero code."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        # Empty queue — get() will raise queue.Empty (timeout behaviour)
        q: queue.Queue[tuple[str, Any]] = queue.Queue()

        mock_process = MagicMock()
        mock_process.pid = 1234
        # First call: alive (before get timeout), second: dead
        mock_process.is_alive.side_effect = [True, False]
        mock_process.exitcode = 1

        ctx = MagicMock()
        ctx.Queue.return_value = q
        ctx.Process.return_value = mock_process

        # Make queue.get raise immediately to simulate timeout
        def _instant_timeout(**kwargs: Any) -> Any:
            raise queue.Empty

        q.get = _instant_timeout  # type: ignore[method-assign]

        with patch("multiprocessing.get_context", return_value=ctx):
            with pytest.raises(SubprocessLoopError, match="exited with code 1"):
                async for _ in runner.run(_make_request()):
                    pass

    @pytest.mark.asyncio
    async def test_returns_cleanly_on_zero_exit_after_timeout(self) -> None:
        """Returns without error when process exits cleanly (code 0)."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        q: queue.Queue[tuple[str, Any]] = queue.Queue()
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.side_effect = [True, False]
        mock_process.exitcode = 0

        ctx = MagicMock()
        ctx.Queue.return_value = q
        ctx.Process.return_value = mock_process

        def _instant_timeout(**kwargs: Any) -> Any:
            raise queue.Empty

        q.get = _instant_timeout  # type: ignore[method-assign]

        with patch("multiprocessing.get_context", return_value=ctx):
            result = []
            async for chunk in runner.run(_make_request()):
                result.append(chunk)

        assert result == []


class TestLocalLoopRunnerCancel:
    """cancel() terminates the subprocess and waits for it to exit."""

    @pytest.mark.asyncio
    async def test_cancel_terminates_process(self) -> None:
        """cancel() calls terminate() then join() on the process."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True
        mock_process.join.return_value = None  # synchronous join
        runner._process = mock_process

        await runner.cancel()

        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_noop_when_no_process(self) -> None:
        """cancel() is a no-op when no process has been started."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)
        # Should not raise
        await runner.cancel()

    @pytest.mark.asyncio
    async def test_cancel_noop_when_process_already_dead(self) -> None:
        """cancel() is a no-op when process is no longer alive."""
        config = _make_config()
        runner = LocalLoopRunner("loop-1", config)

        mock_process = MagicMock()
        mock_process.is_alive.return_value = False
        runner._process = mock_process

        await runner.cancel()

        mock_process.terminate.assert_not_called()
