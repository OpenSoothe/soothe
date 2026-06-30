"""Ephemeral loop garbage collection and shared loop teardown (IG-430)."""

from __future__ import annotations

import logging
import shutil
from typing import Any

from soothe.foundation.loop.state.persistence.directory_manager import (
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
    daemon._thread_registry.cleanup_loop(loop_id)


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
    """
    if metadata.get("status") == "running":
        logger.debug("Skipping ephemeral GC for running loop %s", loop_id)
        return False

    thread_ids = list(metadata.get("thread_ids") or [])
    current_tid = str(metadata.get("current_thread_id") or "").strip()
    if current_tid and current_tid not in thread_ids:
        thread_ids.append(current_tid)

    await _cancel_and_detach_loop(daemon, loop_id)
    await _delete_loop_threads(daemon, thread_ids)
    await _delete_loop_filesystem(loop_id)
    await daemon._persistence_manager.purge_loop_execution_data(loop_id)
    logger.info("Purged ephemeral loop execution data: %s", loop_id)
    return True


async def purge_loop_fully(daemon: Any, loop_id: str, metadata: dict[str, Any] | None) -> None:
    """Full loop deletion (same persistence teardown as ``loop_delete`` RPC)."""
    meta = metadata or await daemon._persistence_manager.get_loop_metadata(loop_id) or {}
    thread_ids = list(meta.get("thread_ids") or [])
    current_tid = str(meta.get("current_thread_id") or "").strip()
    if current_tid and current_tid not in thread_ids:
        thread_ids.append(current_tid)

    try:
        await daemon._query_engine.cancel_loop(loop_id)
    except Exception:
        logger.warning("Failed to cancel running queries for loop %s", loop_id, exc_info=True)

    for cid in list(daemon._session_manager._sessions.keys()):
        await daemon._session_manager.unsubscribe_loop(cid, loop_id)

    await daemon._loop_input_dispatcher.cleanup_loop(loop_id)
    # Release in-memory card ledger; display rows are purged via persistence manager.
    card_manager = getattr(daemon, "_card_manager", None)
    if card_manager is not None:
        try:
            await card_manager.stop_for_loop(loop_id)
        except Exception:
            logger.warning("Failed to release card ledger for loop %s", loop_id, exc_info=True)
    removed_threads = daemon._thread_registry.cleanup_loop(loop_id)
    if removed_threads:
        try:
            from soothe.foundation.core.agent._claude_session import cleanup_claude_sessions
        except ImportError:
            cleanup_claude_sessions = None  # type: ignore[assignment]
        if cleanup_claude_sessions is not None:
            cleanup_claude_sessions(removed_threads)

    await _delete_loop_threads(daemon, thread_ids)
    await _delete_loop_filesystem(loop_id)

    try:
        await daemon._persistence_manager.purge_loop_execution_data(loop_id)
    except Exception as exc:
        logger.error("Failed to purge loop %s from database: %s", loop_id, exc)
        raise
