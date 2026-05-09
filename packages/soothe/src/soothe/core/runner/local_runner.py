"""Subprocess-isolated loop runner using Python multiprocessing (RFC-221)."""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import multiprocessing.context
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from soothe.config.settings import SootheConfig
from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest

if TYPE_CHECKING:
    from soothe.core.runner._runner_shared import StreamChunk

logger = logging.getLogger(__name__)


class SubprocessLoopError(RuntimeError):
    """Raised when the loop subprocess exits with a non-zero exit code."""


def _spawn_safe_config(config: SootheConfig | None) -> SootheConfig:
    """Return a copy of ``config`` safe for ``multiprocessing`` spawn pickling.

    The daemon may have populated runtime caches (chat models, embeddings,
    vector stores) that hold unpickleable synchronization primitives. The
    subprocess only needs declarative settings and rebuilds caches locally.

    Args:
        config: Loaded daemon config, or ``None`` (tests / callers without config)
            to use declarative defaults only.
    """
    base = config if config is not None else SootheConfig()
    return SootheConfig.model_validate(base.model_dump(mode="json"))


def _spawn_safe_request(request: LoopRunRequest) -> LoopRunRequest:
    """Ensure ``model_params`` contains only JSON-round-trippable values."""
    if not request.model_params:
        return request
    safe_params = json.loads(json.dumps(request.model_params, default=str))
    return replace(request, model_params=safe_params)


def _loop_worker(
    config: SootheConfig,
    request: LoopRunRequest,
    queue: Any,  # multiprocessing.Queue — typed as Any for pickle compatibility
) -> None:
    """Top-level worker executed inside the subprocess.

    Must be a top-level function (not a closure) so it is picklable by
    ``multiprocessing`` spawn context.
    """
    import asyncio as _asyncio

    from soothe.core.runner import SootheRunner
    from soothe.core.runner.worker_logging import configure_loop_runner_worker_logging

    configure_loop_runner_worker_logging(config, request.loop_id)

    async def _run() -> None:
        runner = SootheRunner(config)
        try:
            async for chunk in runner.astream(
                request.user_input,
                thread_id=request.thread_id,
                workspace=request.workspace,
                autonomous=request.autonomous,
                max_iterations=request.max_iterations,
                preferred_subagent=request.preferred_subagent,
            ):
                queue.put(("chunk", chunk))
        except Exception as exc:  # noqa: BLE001
            queue.put(("error", exc))
            return
        queue.put(("done", None))

    _asyncio.run(_run())


class LocalLoopRunner:
    """Runs a single agent loop in an isolated ``multiprocessing`` subprocess.

    One instance per ``loop_id``. Created by ``LoopRunnerFactory``.
    """

    def __init__(self, loop_id: str, config: SootheConfig | None) -> None:
        self._loop_id = loop_id
        self._config = config
        self._process: multiprocessing.Process | None = None  # type: ignore[type-arg]

    # LoopRunnerProtocol compliance
    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:  # type: ignore[override]
        ctx = multiprocessing.get_context("spawn")
        queue: Any = ctx.Queue()
        spawn_config = _spawn_safe_config(self._config)
        spawn_request = _spawn_safe_request(request)
        self._process = ctx.Process(
            target=_loop_worker,
            args=(spawn_config, spawn_request, queue),
            daemon=True,
            name=f"loop-{self._loop_id}",
        )
        self._process.start()
        logger.debug(
            "LocalLoopRunner: spawned subprocess pid=%d for loop=%s",
            self._process.pid,
            self._loop_id,
        )

        loop = asyncio.get_event_loop()

        def _get_next() -> tuple[str, Any]:
            # Block for up to 1s so the executor thread is not spinning.
            return queue.get(timeout=1.0)

        while True:
            try:
                kind, payload = await loop.run_in_executor(None, _get_next)
            except Exception:  # queue.get timed out or interrupted
                # Check if the process died unexpectedly.
                if self._process and not self._process.is_alive():
                    exitcode = self._process.exitcode
                    if exitcode is None or exitcode != 0:
                        raise SubprocessLoopError(
                            f"Loop subprocess for {self._loop_id} exited with code {exitcode}"
                        ) from None
                    return
                continue

            if kind == "done":
                return
            if kind == "error":
                raise payload
            # kind == "chunk"
            yield payload

    async def cancel(self) -> None:
        if self._process is None or not self._process.is_alive():
            return
        logger.info("LocalLoopRunner: terminating subprocess pid=%d", self._process.pid)
        self._process.terminate()
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, self._process.join),
                timeout=5.0,
            )
        except TimeoutError:
            logger.warning(
                "LocalLoopRunner: subprocess pid=%d did not exit after 5s; killing",
                self._process.pid,
            )
            self._process.kill()


# Verify structural compliance at import time (no overhead at runtime).
def _assert_protocol() -> None:
    _: LoopRunnerProtocol = LocalLoopRunner.__new__(LocalLoopRunner)  # type: ignore[assignment]


__all__ = ["LocalLoopRunner", "SubprocessLoopError", "_loop_worker"]
