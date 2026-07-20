"""Core events and event registry for Coding CoreAgent protocol events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from soothe_sdk.core.events import (
    LifecycleEvent,
    ProtocolEvent,
    SootheEvent,
)
from soothe_sdk.core.verbosity import VerbosityTier

from .constants import (
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    POLICY_CHECKED,
    POLICY_DENIED,
    STREAM_END,
)

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""


def custom_event(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


class StreamEndEvent(LifecycleEvent):
    """Marks the end of an assistant stream scope (generation, phase, or turn)."""

    type: Literal["soothe.stream.end"] = "soothe.stream.end"
    scope: Literal["generation", "phase", "turn"]
    phase: str | None = None
    reason: str | None = None


class LLMRetryAttemptEvent(LifecycleEvent):
    """LLM retry attempt event for middleware visibility."""

    type: Literal["soothe.cognition.llm.retry.attempt"] = "soothe.cognition.llm.retry.attempt"
    attempt: int
    max_attempts: int
    error_type: str
    thread_id: str | None = None


class MemoryRecalledEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.recalled"] = "soothe.internal.memory.recalled"
    count: int = 0
    query: str = ""


class MemoryStoredEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.stored"] = "soothe.internal.memory.stored"
    id: str = ""
    source_thread: str = ""


class PolicyCheckedEvent(ProtocolEvent):
    type: Literal["soothe.internal.policy.checked"] = "soothe.internal.policy.checked"
    action: str = ""
    verdict: str = ""
    profile: str | None = None


class PolicyDeniedEvent(ProtocolEvent):
    type: Literal["soothe.internal.policy.denied"] = "soothe.internal.policy.denied"
    action: str = ""
    reason: str = ""
    profile: str | None = None


EventHandler = Any


class EventPriority(Enum):
    """Event priority levels for queue overflow management."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass(frozen=True)
class EventMeta:
    """Metadata for a registered event type."""

    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier
    summary_template: str = ""
    priority: EventPriority = EventPriority.NORMAL


_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "internal": VerbosityTier.INTERNAL,
    "lifecycle": VerbosityTier.INTERNAL,
    "protocol": VerbosityTier.INTERNAL,
    "cognition": VerbosityTier.NORMAL,
    "tool": VerbosityTier.INTERNAL,
    "subagent": VerbosityTier.INTERNAL,
    "output": VerbosityTier.NORMAL,
    "error": VerbosityTier.NORMAL,
}


@dataclass
class EventRegistry:
    """Central registry for CoreAgent event types."""

    _by_type: dict[str, EventMeta] = field(default_factory=dict)
    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def register(self, meta: EventMeta) -> None:
        self._by_type[meta.type_string] = meta

    def get_meta(self, event_type: str) -> EventMeta | None:
        return self._by_type.get(event_type)

    def classify(self, event_type: str) -> str:
        segments = event_type.split(".")
        if len(segments) >= 2 and segments[1] == "internal":
            return "internal"
        return segments[1] if len(segments) >= 2 else "unknown"

    def get_verbosity(self, event_type: str) -> VerbosityTier:
        meta = self._by_type.get(event_type)
        if meta:
            return meta.verbosity
        domain = self.classify(event_type)
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.INTERNAL)

    def on(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "")
        handlers = self._handlers.get(etype)
        if handlers:
            for h in handlers:
                h(event)
        elif "*" in self._handlers:
            for h in self._handlers["*"]:
                h(event)


REGISTRY = EventRegistry()


def _reg(
    type_string: str,
    model: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    parts = type_string.split(".")
    if len(parts) >= 2 and parts[1] == "internal":
        domain = "internal"
        component = parts[2] if len(parts) >= 3 else ""
        action = ".".join(parts[3:]) if len(parts) >= 4 else ""
        default_tier = VerbosityTier.INTERNAL
    else:
        domain = parts[1] if len(parts) >= 2 else "unknown"
        component = parts[2] if len(parts) >= 3 else ""
        action = parts[3] if len(parts) >= 4 else ""
        default_tier = _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.INTERNAL)
    v = verbosity if verbosity is not None else default_tier
    REGISTRY.register(
        EventMeta(
            type_string=type_string,
            model=model,
            domain=domain,
            component=component,
            action=action,
            verbosity=v,
            summary_template=summary_template,
            priority=priority,
        )
    )


def register_event(
    event_class: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    """Register an event class with the global event registry."""
    if "type" not in event_class.model_fields:
        msg = f"Event class {event_class.__name__} must have a 'type' field with a default value"
        raise KeyError(msg)

    type_field = event_class.model_fields["type"]
    type_string = type_field.default
    if not isinstance(type_string, str):
        msg = f"Event class {event_class.__name__} 'type' field must have a string default value"
        raise KeyError(msg)

    _reg(
        type_string,
        event_class,
        verbosity=verbosity,
        summary_template=summary_template,
        priority=priority,
    )

    if type_string.startswith("soothe.subagent."):
        from soothe_sdk.core.subagent_wire import register_subagent_wire_event_types

        register_subagent_wire_event_types(type_string)


_reg(
    STREAM_END,
    StreamEndEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Stream end ({scope})",
    priority=EventPriority.HIGH,
)
_reg(
    LLM_RETRY_ATTEMPT,
    LLMRetryAttemptEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="LLM retry {attempt}/{max_attempts} ({error_type})",
    priority=EventPriority.HIGH,
)
_reg(MEMORY_RECALLED, MemoryRecalledEvent, summary_template="{count} items recalled")
_reg(MEMORY_STORED, MemoryStoredEvent, summary_template="Stored memory: {id}")
_reg(POLICY_CHECKED, PolicyCheckedEvent, summary_template="Policy: {verdict}")
_reg(POLICY_DENIED, PolicyDeniedEvent, summary_template="Denied: {reason}")

__all__ = [
    "REGISTRY",
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
    "custom_event",
    "register_event",
]
