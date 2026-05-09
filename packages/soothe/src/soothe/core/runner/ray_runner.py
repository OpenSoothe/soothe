"""Ray-based loop runner — one actor per loop_id (RFC-221).

WARNING: This file imports Ray at module level. It must NEVER be imported
by local-mode code paths. ``LoopRunnerFactory`` guards the import behind
``config.daemon.distributed=True``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

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

        while True:
            kind, payload = await queue.get_async()
            if kind == "done":
                return
            if kind == "error":
                raise payload
            # kind == "chunk"
            yield payload

    async def cancel(self) -> None:
        if self._actor is None:
            return
        logger.info("RayLoopRunner: cancelling actor for loop=%s", self._loop_id[:16])
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(
                    self._actor.cancel.remote().future()  # type: ignore[attr-defined]
                ),
                timeout=5.0,
            )
        except (TimeoutError, Exception):  # noqa: BLE001
            pass
        ray.kill(self._actor)
        self._actor = None


# Structural protocol check.
def _assert_protocol() -> None:
    _: LoopRunnerProtocol = RayLoopRunner.__new__(RayLoopRunner)  # type: ignore[assignment]


__all__ = ["RayLoopRunner"]
