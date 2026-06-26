"""Lightweight probes for loop display history without CoreAgent materialization."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

from soothe.foundation.loop.state.persistence.directory_manager import PersistenceDirectoryManager

logger = logging.getLogger(__name__)

_DERIVABLE_LOG_KINDS = frozenset({"event", "tool_call", "tool_result", "conversation"})


def normalize_log_row(row: Any) -> dict[str, Any]:
    """Normalize a runner thread-log row into a plain dict."""
    if isinstance(row, dict):
        return row
    dump = getattr(row, "model_dump", None)
    if callable(dump):
        try:
            payload = dump(mode="json") if "mode" in dump.__code__.co_varnames else dump()
            if isinstance(payload, dict):
                return payload
        except Exception:
            logger.debug("model_dump failed on activity-log row", exc_info=True)
    return {}


def filter_derivable_log_events(raw_log: list[Any]) -> list[dict[str, Any]]:
    """Return activity-log rows that the card binder can consume."""
    return [
        row
        for row in (normalize_log_row(item) for item in raw_log)
        if row.get("kind") in _DERIVABLE_LOG_KINDS
    ]


async def langgraph_checkpoint_exists(thread_id: str) -> bool:
    """Return True when LangGraph has a checkpoint row for ``thread_id``."""
    db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
    if not db_path.is_file():
        return False

    def _probe() -> bool:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return False
        try:
            cursor = conn.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
                (thread_id,),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            logger.debug(
                "LangGraph checkpoint probe failed for thread %s",
                thread_id,
                exc_info=True,
            )
            return False
        finally:
            conn.close()

    return await asyncio.to_thread(_probe)


__all__ = [
    "filter_derivable_log_events",
    "langgraph_checkpoint_exists",
    "normalize_log_row",
]
