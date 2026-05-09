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

    Selects ``LocalLoopRunner`` (multiprocessing subprocess) or
    ``RayLoopRunner`` (Ray actor) based on ``config.daemon.distributed``.

    Ray is validated at construction time when distributed mode is enabled,
    so startup fails fast with a clear message rather than at first loop.
    """

    def __init__(self, config: SootheConfig) -> None:
        self._config = config
        if config.daemon.distributed:
            try:
                import ray  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "Ray is required for distributed mode. Install with: pip install ray"
                ) from exc
            logger.info("LoopRunnerFactory: distributed mode enabled (Ray actor per loop)")
        else:
            logger.info("LoopRunnerFactory: local mode (multiprocessing subprocess per loop)")

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        """Return a fresh runner instance for ``loop_id``."""
        if self._config.daemon.distributed:
            from soothe.core.runner.ray_runner import RayLoopRunner

            return RayLoopRunner(loop_id, self._config)
        from soothe.core.runner.local_runner import LocalLoopRunner

        return LocalLoopRunner(loop_id, self._config)


__all__ = ["LoopRunnerFactory"]
