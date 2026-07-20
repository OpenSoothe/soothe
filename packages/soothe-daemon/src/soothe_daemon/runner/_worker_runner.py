"""Shared worker-thread SootheRunner lifecycle helpers (IG-506)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.runner import SootheRunner
    from soothe_nano.middleware.identity import IdentityRuntime

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
        logger.debug("[WorkerRunner] Warmed SootheRunner for worker reuse")
        return runner, runner

    runner = SootheRunner(config, identity_runtime=identity_runtime)
    if reuse_runner:
        return runner, runner
    return runner, cached_runner


async def _warmup_worker_core_agent(
    runner: SootheRunner,
    *,
    config: SootheConfig,
    warmup_core_agent: bool,
) -> None:
    """Compile CoreAgent graphs used on the first execute path.

    Worker warmup materializes the primary LazyCoreAgent (with checkpointer) and,
    when ephemeral execute streaming is enabled, the checkpointer-free execute
    twin so the first TUI turn does not pay a second multi-second compile.
    """
    if not warmup_core_agent:
        return

    from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent
    from soothe_nano.agent.core_agent import ephemeral_execute_stream_enabled

    if config.agent.runtime.lazy_core_agent:
        core_agent = runner._core_agent
        if isinstance(core_agent, LazyCoreAgent) and not core_agent.is_materialized:
            await runner._materialize_core_agent()

    if ephemeral_execute_stream_enabled():
        _ = runner._materialized_core_agent().execution_graph


# Backward-compatible alias for tests and external patches.
_materialize_runner_core_agent = _warmup_worker_core_agent


def warmup_worker_runner_on_loop(
    loop: asyncio.AbstractEventLoop,
    *,
    config: SootheConfig,
    reuse_runner: bool,
    warmup_runner: bool,
    warmup_core_agent: bool = True,
    identity_runtime: IdentityRuntime | None = None,
    worker_id: str = "",
) -> SootheRunner | None:
    """Create SootheRunner on a worker loop and optionally materialize CoreAgent.

    Moves the LazyCoreAgent compile cost from the first client request to worker
    startup so interactive clients avoid a multi-second TUI freeze.

    Args:
        loop: Dedicated asyncio loop for the worker thread/process.
        config: Agent configuration.
        reuse_runner: When True, retain the runner for later requests.
        warmup_runner: When True, create the runner eagerly.
        warmup_core_agent: When True, compile CoreAgent during warmup.
        identity_runtime: Optional identity bundle for CoreAgent middleware.
        worker_id: Worker identifier for logging.

    Returns:
        Cached runner when reuse is enabled, otherwise ``None``.
    """
    if not (reuse_runner and warmup_runner):
        return None

    cached_runner, _ = acquire_worker_runner(
        config=config,
        cached_runner=None,
        reuse_runner=reuse_runner,
        warmup_runner=warmup_runner,
        identity_runtime=identity_runtime,
    )

    if not warmup_core_agent:
        return cached_runner

    materialize_start = time.perf_counter()
    try:
        if config.skillify.enabled:
            from soothe_daemon.skillify import start_skillify_service

            loop.run_until_complete(start_skillify_service(config))

        loop.run_until_complete(
            _warmup_worker_core_agent(
                cached_runner,
                config=config,
                warmup_core_agent=True,
            )
        )
        materialize_ms = (time.perf_counter() - materialize_start) * 1000
        logger.info(
            "[WorkerRunner] Warmed CoreAgent for worker %s in %.1fms",
            worker_id or "unknown",
            materialize_ms,
        )
    except Exception:
        logger.exception(
            "[WorkerRunner] CoreAgent warmup failed for worker %s; will retry on first request",
            worker_id or "unknown",
        )

    return cached_runner
