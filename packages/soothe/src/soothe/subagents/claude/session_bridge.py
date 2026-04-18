"""Map Soothe LangGraph threads to Claude Agent SDK session ids (IG-202).

Persists ``cwd -> session_uuid`` in thread metadata (durability) and mirrors in
process memory for fast lookup within a run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from soothe.protocols.durability import ThreadMetadata

logger = logging.getLogger(__name__)

_memory_claude_sessions: dict[tuple[str, str], str] = {}
_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _lock_for_key(key: tuple[str, str]) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def resolve_resume_session_id(
    *,
    thread_id: str | None,
    cwd: str,
    claude_sessions_from_config: dict[str, str] | None,
) -> str | None:
    """Return Claude session UUID to pass as ``ClaudeAgentOptions.resume``, if any."""
    if not thread_id:
        if claude_sessions_from_config:
            return claude_sessions_from_config.get(cwd)
        return None
    key = (thread_id, cwd)
    async with _lock_for_key(key):
        mem = _memory_claude_sessions.get(key)
    if mem:
        return mem
    if claude_sessions_from_config:
        return claude_sessions_from_config.get(cwd)
    return None


async def record_claude_session(
    *,
    thread_id: str | None,
    cwd: str,
    session_id: str | None,
    durability: Any | None,
) -> None:
    """Update memory cache and durability metadata with the latest session id."""
    if not session_id or not cwd:
        return
    if thread_id:
        key = (thread_id, cwd)
        async with _lock_for_key(key):
            _memory_claude_sessions[key] = session_id
    if durability is None or not thread_id:
        return
    try:
        info = await durability.get_thread(thread_id)
        if info is None:
            logger.debug(
                "Claude session not persisted: thread %s missing from durability store",
                thread_id,
            )
            return
        merged = dict(info.metadata.claude_sessions)
        merged[cwd] = session_id
        await durability.update_thread_metadata(thread_id, ThreadMetadata(claude_sessions=merged))
    except Exception:
        logger.debug("Failed to persist Claude session id for thread %s", thread_id, exc_info=True)
