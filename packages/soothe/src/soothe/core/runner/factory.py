"""LoopRunnerFactory — creates per-loop runner instances (RFC-221)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.protocols.runner import LoopRunnerProtocol

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig

logger = logging.getLogger(__name__)


class LoopRunnerFactory:
    """Creates a ``LoopRunnerProtocol`` instance for each new ``loop_id``.

    Selects runner implementation based on config:

    - ``worker_pool.enabled=true`` → ``PoolLoopRunner`` (persistent subprocess pool)
    - ``distributed=true`` → ``RayLoopRunner`` (Ray actor per loop)
    - default → ``LocalLoopRunner`` (spawn subprocess per loop)

    Ray is validated at construction time when distributed mode is enabled,
    so startup fails fast with a clear message rather than at first loop.
    """

    def __init__(self, config: SootheConfig) -> None:
        self._config = config
        self._pool_initialized = False

        if config.daemon.worker_pool.enabled:
            logger.info(
                "LoopRunnerFactory: pool mode enabled (min=%d, max=%d workers, max_requests=%d)",
                config.daemon.worker_pool.min_pool_size,
                config.daemon.worker_pool.max_pool_size,
                config.daemon.worker_pool.max_requests_per_worker,
            )
        elif config.daemon.distributed.enabled:
            try:
                import ray  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "Ray is required for distributed mode. Install with: pip install ray"
                ) from exc
            logger.info("LoopRunnerFactory: distributed mode enabled (Ray actor per loop)")
        else:
            logger.info("LoopRunnerFactory: local mode (spawn subprocess per loop)")

    async def initialize_pool(self) -> None:
        """Pre-warm worker pool if enabled.

        Called by SootheDaemon.start() during startup.
        """
        if self._config.daemon.worker_pool.enabled and not self._pool_initialized:
            from soothe.core.runner.pool_runner import WorkerPool

            await WorkerPool.get_shared_instance(self._config)
            self._pool_initialized = True
            logger.info("LoopRunnerFactory: worker pool pre-warmed")

    async def shutdown_pool(self) -> None:
        """Shutdown worker pool if active.

        Called by SootheDaemon.stop() during shutdown.
        """
        if self._pool_initialized:
            from soothe.core.runner.pool_runner import WorkerPool

            await WorkerPool.close_shared_instance()
            self._pool_initialized = False
            logger.info("LoopRunnerFactory: worker pool shutdown")

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        """Return a runner instance for ``loop_id``."""
        if self._config.daemon.worker_pool.enabled:
            from soothe.core.runner.pool_runner import PoolLoopRunner

            return PoolLoopRunner(loop_id, self._config)
        if self._config.daemon.distributed.enabled:
            from soothe.core.runner.ray_runner import RayLoopRunner

            return RayLoopRunner(loop_id, self._config)
        from soothe.core.runner.local_runner import LocalLoopRunner

        return LocalLoopRunner(loop_id, self._config)


__all__ = ["LoopRunnerFactory"]
