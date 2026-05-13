"""LoopRunnerFactory — creates per-loop runner instances (RFC-221)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.protocols.runner import LoopRunnerProtocol

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe_daemon.config import SootheDaemonConfig

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

    def __init__(self, daemon_config: SootheDaemonConfig, agent_config: SootheConfig) -> None:
        self._daemon_config = daemon_config
        self._agent_config = agent_config
        self._pool_initialized = False

        if daemon_config.worker_pool.enabled:
            logger.info(
                "LoopRunnerFactory: pool mode enabled (min=%d, max=%d workers, max_requests=%d)",
                daemon_config.worker_pool.min_pool_size,
                daemon_config.worker_pool.max_pool_size,
                daemon_config.worker_pool.max_requests_per_worker,
            )
        elif daemon_config.distributed.enabled:
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
        if self._daemon_config.worker_pool.enabled and not self._pool_initialized:
            from soothe_daemon.runner.pool_runner import WorkerPool

            await WorkerPool.get_shared_instance(self._agent_config, self._daemon_config)
            self._pool_initialized = True
            logger.info("LoopRunnerFactory: worker pool pre-warmed")

    async def shutdown_pool(self) -> None:
        """Shutdown worker pool if active.

        Called by SootheDaemon.stop() during shutdown.
        """
        if self._pool_initialized:
            from soothe_daemon.runner.pool_runner import WorkerPool

            await WorkerPool.close_shared_instance()
            self._pool_initialized = False
            logger.info("LoopRunnerFactory: worker pool shutdown")

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        """Return a runner instance for ``loop_id``."""
        if self._daemon_config.worker_pool.enabled:
            from soothe_daemon.runner.pool_runner import PoolLoopRunner

            return PoolLoopRunner(loop_id, self._agent_config, self._daemon_config)
        if self._daemon_config.distributed.enabled:
            from soothe_daemon.runner.ray_runner import RayLoopRunner

            return RayLoopRunner(loop_id, self._agent_config)
        from soothe.core.runner.local_runner import LocalLoopRunner

        return LocalLoopRunner(loop_id, self._agent_config)


__all__ = ["LoopRunnerFactory"]
