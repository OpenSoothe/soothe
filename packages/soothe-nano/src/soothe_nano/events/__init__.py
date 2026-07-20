"""Event system package — CoreAgent protocol events and registry helpers."""

from __future__ import annotations

from soothe_sdk.core.verbosity import VerbosityTier

from .catalog import (
    REGISTRY,
    EventMeta,
    EventPriority,
    EventRegistry,
    LLMRetryAttemptEvent,
    MemoryRecalledEvent,
    MemoryStoredEvent,
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    StreamChunk,
    StreamEndEvent,
    custom_event,
    register_event,
)
from .constants import (
    ERROR,
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    POLICY_CHECKED,
    POLICY_DENIED,
    STREAM_END,
)

__all__ = [
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "REGISTRY",
    "STREAM_END",
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "LLMRetryAttemptEvent",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "PolicyCheckedEvent",
    "PolicyDeniedEvent",
    "StreamChunk",
    "StreamEndEvent",
    "VerbosityTier",
    "custom_event",
    "register_event",
]
