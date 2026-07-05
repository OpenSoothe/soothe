"""Shared utilities for worker runners (subprocess pool, thread pool, Ray actors).

Functions extracted from local_runner.py for reuse across runner implementations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.protocols.runner import LoopRunRequest

logger = logging.getLogger(__name__)

_DEFAULT_ORPHAN_TASK_CANCEL_TIMEOUT_SECONDS = 30.0


def spawn_safe_config(config: SootheConfig | None) -> SootheConfig:
    """Return a copy of ``config`` safe for ``multiprocessing`` spawn pickling.

    The daemon may have populated runtime caches (chat models, embeddings,
    vector stores) that hold unpickleable synchronization primitives. The
    subprocess only needs declarative settings and rebuilds caches locally.

    Args:
        config: Loaded daemon config, or ``None`` (tests / callers without config)
            to use declarative defaults only.
    """
    from soothe.config.settings import SootheConfig

    base = config if config is not None else SootheConfig()
    return SootheConfig.model_validate(base.model_dump(mode="json"))


def spawn_safe_request(request: LoopRunRequest) -> LoopRunRequest:
    """Ensure ``model_params`` contains only JSON-round-trippable values."""
    if not request.model_params:
        return request
    safe_params = json.loads(json.dumps(request.model_params, default=str))
    return replace(request, model_params=safe_params)


def cancel_orphan_loop_tasks(
    loop: asyncio.AbstractEventLoop,
    *,
    timeout_seconds: float = _DEFAULT_ORPHAN_TASK_CANCEL_TIMEOUT_SECONDS,
) -> None:
    """Cancel asyncio tasks left behind after a worker request completes.

    Leaked background tasks (for example async checkpoint flush workers when
    ``StrangeLoopStateManager.close()`` did not run) can corrupt the worker
    event loop on the next ``run_until_complete`` call.

    Args:
        loop: Dedicated worker event loop.
        timeout_seconds: Maximum time to wait for cancelled tasks to finish.
    """
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not pending:
        return

    for task in pending:
        task.cancel()

    async def _gather_pending() -> None:
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        loop.run_until_complete(asyncio.wait_for(_gather_pending(), timeout=timeout_seconds))
    except TimeoutError:
        still_running = [task for task in pending if not task.done()]
        if still_running:
            task_names = [
                task.get_name() if task.get_name() else repr(task) for task in still_running
            ]
            logger.warning(
                "cancel_orphan_loop_tasks: %d task(s) still running after %.1fs: %s; "
                "worker loop may retain leaked background work",
                len(still_running),
                timeout_seconds,
                ", ".join(task_names),
            )


__all__ = ["cancel_orphan_loop_tasks", "spawn_safe_config", "spawn_safe_request"]
