"""Shared worker-thread SootheRunner lifecycle helpers (IG-506)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.middleware.identity import IdentityRuntime
    from soothe.runner import SootheRunner

logger = logging.getLogger(__name__)


def acquire_worker_runner(
    *,
    config: SootheConfig,
    cached_runner: SootheRunner | None,
    reuse_runner: bool,
    warmup_runner: bool,
    identity_runtime: IdentityRuntime | None = None,
) -> tuple[SootheRunner, SootheRunner | None]:
    """Return a runner for this request and updated cache.

    Args:
        config: Agent configuration.
        cached_runner: Runner retained from prior requests on this worker.
        reuse_runner: When True, reuse ``cached_runner`` between requests.
        warmup_runner: When True and no cache exists, create runner eagerly.
        identity_runtime: Optional identity bundle for CoreAgent middleware.

    Returns:
        Tuple of (runner_for_request, updated_cached_runner).
    """
    from soothe.runner import SootheRunner

    if reuse_runner and cached_runner is not None:
        cached_runner.prepare_for_request()
        return cached_runner, cached_runner

    if cached_runner is None and warmup_runner and reuse_runner:
        runner = SootheRunner(config, identity_runtime=identity_runtime)
        logger.info("[WorkerRunner] Warmed SootheRunner for worker reuse (IG-506)")
        return runner, runner

    runner = SootheRunner(config, identity_runtime=identity_runtime)
    if reuse_runner:
        return runner, runner
    return runner, cached_runner
