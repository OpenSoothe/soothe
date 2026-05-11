"""Ray-based loop runner — one actor per loop_id (RFC-221).

WARNING: This file imports Ray at module level. It must NEVER be imported
by local-mode code paths. ``LoopRunnerFactory`` guards the import behind
``config.daemon.distributed=True``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import ray
from ray.util.queue import Queue

from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.core.runner._runner_shared import StreamChunk

logger = logging.getLogger(__name__)


class RayLoopRunner:
    """Manages one ``LoopRunnerActor`` (Ray remote actor) per ``loop_id``.

    One instance per loop. Created by ``LoopRunnerFactory`` when
    ``config.daemon.distributed=True``.
    """

    def __init__(self, loop_id: str, config: SootheConfig) -> None:
        self._loop_id = loop_id
        self._config = config
        self._actor: ray.actor.ActorHandle | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:  # type: ignore[override]
        from soothe.core.runner.ray_actor import LoopRunnerActor

        self._actor = LoopRunnerActor.remote(self._config)
        queue: Queue = Queue(maxsize=1000)

        # Non-blocking remote call — actor pushes chunks into queue.
        self._actor.run.remote(request, queue)
        logger.debug("RayLoopRunner: actor started for loop=%s", self._loop_id[:16])

        try:
            while True:
                kind, payload = await queue.get_async()
                if kind == "done":
                    return
                if kind == "error":
                    raise payload
                # kind == "chunk"
                yield payload
        except asyncio.CancelledError:
            logger.debug("RayLoopRunner: run cancelled, exiting gracefully")
            raise

    async def cancel(self) -> None:
        if self._actor is None:
            return
        logger.info("RayLoopRunner: cancelling actor for loop=%s", self._loop_id[:16])

        # Ask actor to cancel gracefully — it should emit "done" to queue.
        cancel_ref = self._actor.cancel.remote()

        # Wait for actor's cancel method to complete (it sets _released and emits "done").
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(cancel_ref.future()),  # type: ignore[attr-defined]
                timeout=10.0,
            )
        except (TimeoutError, Exception):  # noqa: BLE001
            logger.warning("RayLoopRunner: actor cancel timed out or failed")

        # Brief grace period for driver to receive pending queue items before hard kill.
        await asyncio.sleep(0.5)

        # Hard kill actor as cleanup.
        try:
            ray.kill(self._actor)
        except Exception:  # noqa: BLE001
            pass
        self._actor = None

    async def forward_interrupt_resume(self, loop_id: str, payload: dict[str, Any]) -> None:
        """Not supported for Ray runner."""
        logger.warning("RayLoopRunner: interrupt resume not supported (loop=%s)", loop_id)


# Structural protocol check.
def _assert_protocol() -> None:
    _: LoopRunnerProtocol = RayLoopRunner.__new__(RayLoopRunner)  # type: ignore[assignment]


__all__ = ["RayLoopRunner"]
