"""Stream event type constants and helper builders for soothe.* events."""

from __future__ import annotations

from typing import Any

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

STREAM_CHUNK_LEN = 3
MSG_PAIR_LEN = 2

# Protocol event type prefixes
SESSION_STARTED = "soothe.session.started"
SESSION_ENDED = "soothe.session.ended"
CONTEXT_PROJECTED = "soothe.context.projected"
CONTEXT_INGESTED = "soothe.context.ingested"
MEMORY_RECALLED = "soothe.memory.recalled"
MEMORY_STORED = "soothe.memory.stored"
PLAN_CREATED = "soothe.plan.created"
PLAN_REFLECTED = "soothe.plan.reflected"
POLICY_CHECKED = "soothe.policy.checked"
POLICY_DENIED = "soothe.policy.denied"
THREAD_CREATED = "soothe.thread.created"
THREAD_RESUMED = "soothe.thread.resumed"
THREAD_SAVED = "soothe.thread.saved"
ERROR = "soothe.error"


def custom_event(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)
