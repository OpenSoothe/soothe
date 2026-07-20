"""Event system package — CoreAgent protocol events and registry helpers."""

from __future__ import annotations

from soothe_sdk.core.verbosity import VerbosityTier

from .catalog import (
    REGISTRY,
    ConfigReloadedEvent,
    DaemonHeartbeatEvent,
    EventMeta,
    EventPriority,
    EventRegistry,
    MemoryRecalledEvent,
    MemoryStoredEvent,
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    StreamChunk,
    custom_event,
    register_event,
)
from .constants import (
    CONFIG_RELOADED,
    DAEMON_HEARTBEAT,
    ERROR,
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    POLICY_CHECKED,
    POLICY_DENIED,
    STREAM_END,
)

__all__ = [
    "CONFIG_RELOADED",
    "DAEMON_HEARTBEAT",
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "REGISTRY",
    "STREAM_END",
    "ConfigReloadedEvent",
    "DaemonHeartbeatEvent",
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "PolicyCheckedEvent",
    "PolicyDeniedEvent",
    "StreamChunk",
    "VerbosityTier",
    "custom_event",
    "register_event",
]
