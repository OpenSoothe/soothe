"""Ephemeral loop garbage collection and shared loop teardown."""

from __future__ import annotations

import logging
import shutil
from typing import Any

from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)

logger = logging.getLogger(__name__)


async def _cancel_and_detach_loop(daemon: Any, loop_id: str) -> None:
    """Cancel in-flight work and detach clients for a loop."""
    try:
        await daemon._query_engine.cancel_loop(loop_id)
    except Exception:
        logger.warning("Failed to cancel running queries for loop %s", loop_id, exc_info=True)

    for cid in list(daemon._session_manager._sessions.keys()):
        await daemon._session_manager.unsubscribe_loop(cid, loop_id)

    await daemon._loop_input_dispatcher.cleanup_loop(loop_id)
    budget = getattr(daemon, "_loop_broadcast_budget", None)
    if budget is not None:
        budget.drop_loop(loop_id)
    daemon._thread_registry.cleanup_loop(loop_id)


async def _collect_loop_thread_ids(daemon: Any, loop_id: str) -> list[str]:
    """Find all persisted thread ids belonging to ``loop_id``.

    Per IG-764, loop metadata no longer indexes fork threads. The main thread
    is the bare ``loop_id``; every fork (execute-step, synth, intake) shares
    the ``{loop_id}__`` prefix. Scan the durability layer to find them so GC
    can delete the full set. Falls back to ``[loop_id]`` when the runner or
    scan is unavailable.
    """
    runner = getattr(daemon, "_runner", None)
    if runner is None:
        return [loop_id]
    try:
        threads = await runner.list_threads()
    except Exception:
        logger.debug("list_threads unavailable during GC; falling back to loop_id", exc_info=True)
        return [loop_id]
    prefix = f"{loop_id}__"
    fork_ids = [
        t["thread_id"]
        for t in threads
        if isinstance(t, dict)
        and isinstance(t.get("thread_id"), str)
        and t["thread_id"].startswith(prefix)
        and t["thread_id"] != loop_id
    ]
    return [loop_id, *fork_ids]


async def _delete_loop_threads(daemon: Any, thread_ids: list[str]) -> None:
    """Delete LangGraph thread persistence for each thread id."""
    runner = getattr(daemon, "_runner", None)
    if runner is None:
        return
    for tid in thread_ids:
        tid_str = str(tid).strip()
        if not tid_str:
            continue
        try:
            await runner.delete_persisted_thread(tid_str)
        except Exception:
            logger.warning(
                "Failed to delete persisted thread %s during loop cleanup",
                tid_str,
                exc_info=True,
            )


async def _delete_loop_filesystem(loop_id: str) -> None:
    """Remove loop-scoped data under ``data/loops/{loop_id}`` (not workspace sandboxes)."""
    loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
    if loop_dir.exists():
        shutil.rmtree(loop_dir)
        logger.info("Deleted loop directory: %s", loop_id)


async def purge_loop_execution_data(daemon: Any, loop_id: str, metadata: dict[str, Any]) -> bool:
    """Remove execution persistence for a loop; keep workspace directories.

    Args:
        daemon: ``SootheDaemon`` instance.
        loop_id: Loop identifier.
        metadata: Loop metadata dict (thread ids, status).

    Returns:
        True if purge completed, False if skipped (e.g. still running).

    The purge gate is liveness-aware: a row still marked ``status="running"``
    is only protected when an active runner can be confirmed for the loop.
    This reclaims zombie loops whose persisted status was never flipped to
    ``idle`` because the runner died without a teardown hook. The liveness
    check mirrors ``auto_resume._loop_has_active_runner``.
    """
    from soothe_daemon.runtime.auto_resume import _loop_has_active_runner

    if _loop_has_active_runner(daemon, loop_id):
        logger.debug("Skipping ephemeral GC for loop with active runner: %s", loop_id)
        return False

    await _cancel_and_detach_loop(daemon, loop_id)
    thread_ids = await _collect_loop_thread_ids(daemon, loop_id)
    await _delete_loop_threads(daemon, thread_ids)
    await _delete_loop_filesystem(loop_id)
    await daemon._persistence_manager.purge_loop_execution_data(loop_id)
    logger.info("Purged ephemeral loop execution data: %s", loop_id)
    return True


async def purge_loop_fully(daemon: Any, loop_id: str, metadata: dict[str, Any] | None) -> None:
    """Full loop deletion (same persistence teardown as ``loop_delete`` RPC)."""
    try:
        await daemon._query_engine.cancel_loop(loop_id)
    except Exception:
        logger.warning("Failed to cancel running queries for loop %s", loop_id, exc_info=True)

    for cid in list(daemon._session_manager._sessions.keys()):
        await daemon._session_manager.unsubscribe_loop(cid, loop_id)

    await daemon._loop_input_dispatcher.cleanup_loop(loop_id)
    budget = getattr(daemon, "_loop_broadcast_budget", None)
    if budget is not None:
        budget.drop_loop(loop_id)
    # Release in-memory card ledger; display rows are purged via persistence manager.
    card_manager = getattr(daemon, "_card_manager", None)
    if card_manager is not None:
        try:
            await card_manager.stop_for_loop(loop_id)
        except Exception:
            logger.warning("Failed to release card ledger for loop %s", loop_id, exc_info=True)
    daemon._thread_registry.cleanup_loop(loop_id)

    thread_ids = await _collect_loop_thread_ids(daemon, loop_id)
    await _delete_loop_threads(daemon, thread_ids)
    await _delete_loop_filesystem(loop_id)

    try:
        await daemon._persistence_manager.purge_loop_execution_data(loop_id)
    except Exception as exc:
        logger.error("Failed to purge loop %s from database: %s", loop_id, exc)
        raise
