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

    Selects runner implementation based on config (exactly one must be enabled):

    - ``worker_pool.enabled=true`` → ``PoolLoopRunner`` (persistent subprocess pool)
    - ``thread_pool.enabled=true`` → ``ThreadLoopRunner`` (persistent thread pool)
    - ``distributed.enabled=true`` → ``RayLoopRunner`` (Ray actor per loop)

    Validation ensures exactly one mode is enabled at startup.
    """

    def __init__(self, daemon_config: SootheDaemonConfig, agent_config: SootheConfig) -> None:
        self._daemon_config = daemon_config
        self._agent_config = agent_config
        self._pool_initialized = False

        # Validate exactly one runner mode is enabled
        mode = daemon_config.validate_runner_mode()
        self._mode = mode

        if mode == "worker_pool":
            logger.info(
                "LoopRunnerFactory: process pool mode (min=%d, max=%d workers, max_requests=%d)",
                daemon_config.worker_pool.min_pool_size,
                daemon_config.worker_pool.max_pool_size,
                daemon_config.worker_pool.max_requests_per_worker,
            )
        elif mode == "thread_pool":
            logger.info(
                "LoopRunnerFactory: thread pool mode (min=%d, max=%d threads, max_requests=%d)",
                daemon_config.thread_pool.min_pool_size,
                daemon_config.thread_pool.max_pool_size,
                daemon_config.thread_pool.max_requests_per_thread,
            )
        elif mode == "distributed":
            try:
                import ray  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "Ray is required for distributed mode. Install with: pip install ray"
                ) from exc
            logger.info("LoopRunnerFactory: distributed mode (Ray actor per loop)")

    async def initialize_pool(self) -> None:
        """Pre-warm worker pool if enabled.

        Called by SootheDaemon.start() during startup.
        """
        if self._pool_initialized:
            return

        if self._mode == "worker_pool":
            from soothe_daemon.runner.pool_runner import WorkerPool

            await WorkerPool.get_shared_instance(self._agent_config, self._daemon_config)
            self._pool_initialized = True
            logger.info("LoopRunnerFactory: process worker pool pre-warmed")
        elif self._mode == "thread_pool":
            from soothe_daemon.runner.thread_runner import ThreadPool

            await ThreadPool.get_shared_instance(self._agent_config, self._daemon_config)
            self._pool_initialized = True
            logger.info("LoopRunnerFactory: thread pool pre-warmed")

    async def shutdown_pool(self) -> None:
        """Shutdown worker pool if active.

        Called by SootheDaemon.stop() during shutdown.
        """
        if not self._pool_initialized:
            return

        if self._mode == "worker_pool":
            from soothe_daemon.runner.pool_runner import WorkerPool

            await WorkerPool.close_shared_instance()
            logger.info("LoopRunnerFactory: process worker pool shutdown")
        elif self._mode == "thread_pool":
            from soothe_daemon.runner.thread_runner import ThreadPool

            await ThreadPool.close_shared_instance()
            logger.info("LoopRunnerFactory: thread pool shutdown")

        self._pool_initialized = False

        from soothe_daemon.persistence.pools import close_shared_postgres_pools

        await close_shared_postgres_pools()

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        """Return a runner instance for ``loop_id``."""
        if self._mode == "worker_pool":
            from soothe_daemon.runner.pool_runner import PoolLoopRunner

            return PoolLoopRunner(loop_id, self._agent_config, self._daemon_config)
        if self._mode == "thread_pool":
            from soothe_daemon.runner.thread_runner import ThreadLoopRunner

            return ThreadLoopRunner(loop_id, self._agent_config, self._daemon_config)
        # mode == "distributed"
        from soothe_daemon.runner.ray_runner import RayLoopRunner

        return RayLoopRunner(loop_id, self._agent_config)


__all__ = ["LoopRunnerFactory"]
