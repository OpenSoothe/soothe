"""Canonical event registry for the Soothe stack.

This module owns the single source of truth for event metadata types
(``EventPriority`` / ``EventMeta`` / ``EventRegistry``) and the process-wide
``REGISTRY`` singleton. nano, the host (``soothe.foundation.events``), and the
daemon all register into and read from this registry, so event type strings
have one authoritative index regardless of which package defined them.

The registry is structural metadata + handler dispatch; it is intentionally
free of host-only concerns (wire broadcasting, daemon bus routing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic_core import PydanticUndefined

from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

EventHandler = Any  # Callable[[dict[str, Any]], None]


class EventPriority(Enum):
    """Event priority levels for queue overflow management.

    Higher priority events are processed first and less likely to be dropped
    when queues are near capacity.

    Priority levels:
    - CRITICAL: Never dropped, block if queue full (errors, cancellation)
    - HIGH: Rarely dropped (tool results, subagent output)
    - NORMAL: Standard priority (heartbeat, status updates)
    - LOW: First to drop under pressure (debug, trace events)
    """

    CRITICAL = 0  # Never drop, block if necessary
    HIGH = 1  # Rarely drop (tool/subagent results)
    NORMAL = 2  # Standard priority (heartbeat, status)
    LOW = 3  # First to drop (debug/trace)


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


# Default verbosity tier per top-level domain. The domain is the second
# segment of the type string (``soothe.<domain>.<component>.<action>``); the
# ``internal`` domain maps to the ``soothe.internal.*`` namespace.
_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "internal": VerbosityTier.INTERNAL,
    "lifecycle": VerbosityTier.INTERNAL,
    "protocol": VerbosityTier.INTERNAL,
    "cognition": VerbosityTier.NORMAL,
    "loop": VerbosityTier.NORMAL,  # Loop relay events (clarification relay)
    "tool": VerbosityTier.INTERNAL,  # tool display routed via LangChain on_tool_call
    "subagent": VerbosityTier.INTERNAL,  # subagent internals hidden from clients
    "output": VerbosityTier.NORMAL,
    "error": VerbosityTier.NORMAL,
    "agentic": VerbosityTier.NORMAL,
}


@dataclass
class EventRegistry:
    """Central registry for all Soothe event types.

    Provides O(1) lookup by event type string, structural domain
    classification, verbosity resolution, and handler dispatch.
    """

    _by_type: dict[str, EventMeta] = field(default_factory=dict)
    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def register(self, meta: EventMeta) -> None:
        """Register an event type with its metadata."""
        self._by_type[meta.type_string] = meta

    def get_meta(self, event_type: str) -> EventMeta | None:
        """Look up metadata for an event type string."""
        return self._by_type.get(event_type)

    def classify(self, event_type: str) -> str:
        """Return the domain from an event type string via ``split('.')[1]``."""
        segments = event_type.split(".")
        _min_segments = 2
        if len(segments) >= _min_segments and segments[1] == "internal":
            return "internal"
        return segments[1] if len(segments) >= _min_segments else "unknown"

    def get_verbosity(self, event_type: str) -> VerbosityTier:
        """Return the VerbosityTier for an event type."""
        meta = self._by_type.get(event_type)
        if meta:
            return meta.verbosity
        domain = self.classify(event_type)
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.INTERNAL)

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type (or ``*`` for fallback)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: dict[str, Any]) -> None:
        """Dispatch an event dict to registered handlers."""
        etype = event.get("type", "")
        handlers = self._handlers.get(etype)
        if handlers:
            for h in handlers:
                h(event)
        elif "*" in self._handlers:
            for h in self._handlers["*"]:
                h(event)


# Process-wide singleton. nano, host, and daemon all share this instance.
REGISTRY = EventRegistry()


def _split_domain(type_string: str) -> tuple[str, str, str, VerbosityTier]:
    """Return ``(domain, component, action, default_tier)`` for a type string."""
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
    return domain, component, action, default_tier


def _reg(
    type_string: str,
    model: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    """Register ``model`` under ``type_string`` into the shared ``REGISTRY``.

    Internal helper for core event registration. The domain/component/action
    are derived structurally from the type string; ``verbosity`` overrides the
    domain default when provided.
    """
    domain, component, action, default_tier = _split_domain(type_string)
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
    verbosity: VerbosityTier | str | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    """Register an event class with the shared global registry.

    Auto-extracts the type string from the event class's Pydantic ``type``
    field and applies domain-appropriate defaults. For ``soothe.subagent.*``
    types, also allowlists the wire type via
    ``register_subagent_wire_event_types``.

    Usage::

        from soothe_sdk.core import register_event, EventPriority
        from soothe_sdk.core.events import SubagentEvent


        class MyCustomEvent(SubagentEvent):
            type: str = "soothe.subagent.myplugin.custom"
            data: str


        register_event(
            MyCustomEvent,
            summary_template="Custom event: {data}",
            priority=EventPriority.HIGH,
        )

    Args:
        event_class: Event class to register (must have a ``type`` field with a
            string default value).
        verbosity: Verbosity tier override. If not provided, inferred from the
            domain. Accepts a ``VerbosityTier`` or a legacy string alias
            (``quiet``/``normal`` → NORMAL, ``detailed``/``debug``/``internal``
            → INTERNAL).
        summary_template: Optional template for event summaries (supports
            ``{field}`` interpolation).
        priority: Event priority for queue overflow management. Default:
            NORMAL.

    Raises:
        KeyError: If the event class has no ``type`` field with a string
            default value.
    """
    model_fields = getattr(event_class, "model_fields", None)
    if model_fields is None:
        msg = f"Event class {event_class.__name__} must be a Pydantic v2 model with a 'type' field"
        raise KeyError(msg)

    type_field = model_fields.get("type")
    if type_field is None:
        msg = f"Event class {event_class.__name__} must have a 'type' field with a default value"
        raise KeyError(msg)

    type_string = type_field.default
    if type_string is PydanticUndefined or type_string is None:
        msg = f"Event class {event_class.__name__} 'type' field must have a default value"
        raise KeyError(msg)
    if not isinstance(type_string, str):
        msg = f"Event class {event_class.__name__} 'type' field must have a string default value"
        raise KeyError(msg)

    if verbosity is None:
        verbosity_tier: VerbosityTier | None = None
    elif isinstance(verbosity, str):
        verbosity_map = {
            "quiet": VerbosityTier.NORMAL,
            "normal": VerbosityTier.NORMAL,
            "detailed": VerbosityTier.INTERNAL,
            "debug": VerbosityTier.INTERNAL,
            "internal": VerbosityTier.INTERNAL,
        }
        verbosity_tier = verbosity_map.get(verbosity.lower(), VerbosityTier.NORMAL)
    else:
        verbosity_tier = verbosity

    _reg(
        type_string,
        event_class,
        verbosity=verbosity_tier,
        summary_template=summary_template,
        priority=priority,
    )

    if type_string.startswith("soothe.subagent."):
        from soothe_sdk.core.subagent_wire import register_subagent_wire_event_types

        register_subagent_wire_event_types(type_string)


__all__ = [
    "EventHandler",
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "REGISTRY",
    "register_event",
]
