"""Server-side wire visibility rules (internal types are never sent to clients)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.core.verbosity import VerbosityTier, should_show
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH

if TYPE_CHECKING:
    from soothe.core.events import EventMeta

_INTERNAL_PREFIX = "soothe.internal."

# Catalog or wire event types always delivered inside ``type: event`` envelopes.
_ALWAYS_CLIENT_WIRE_INNER_TYPES = frozenset(
    {
        TOOL_CALL_UPDATES_BATCH,
        STREAM_TOOL_CALL_UPDATE,
    }
)

# Wire envelopes that are always delivered (protocol/control, not catalog-gated).
_ALWAYS_CLIENT_WIRE_TOP_TYPES = frozenset(
    {
        "status",
        "error",
        "command_response",
        TOOL_CALL_UPDATES_BATCH,
        "event_batch",
        "replay_complete",
        "loop_reattached",
        "history_replay",
        "subscription_confirmed",
        "daemon_ready",
        "loop_input_response",
        "loop_subscribe_response",
        "loop_new_response",
    }
)

# Clients always receive normal-tier-or-quieter catalog events only (IG-343).
_CLIENT_WIRE_VERBOSITY_CEILING: VerbosityLevel = "normal"


def is_client_broadcast_event_type(type_str: str | None) -> bool:
    """Return True if a catalog event type may be sent to WebSocket clients."""
    if not type_str:
        return True
    return not type_str.startswith(_INTERNAL_PREFIX)


def resolve_event_verbosity_tier(
    event_type: str | None,
    event_meta: EventMeta | None = None,
) -> VerbosityTier | None:
    """Resolve the verbosity tier for a catalog or wire event type."""
    if event_meta is not None:
        return event_meta.verbosity
    if not event_type:
        return None
    if event_type.startswith("soothe."):
        from soothe.core.events.catalog import REGISTRY

        return REGISTRY.get_verbosity(event_type)
    from soothe_sdk.ux.classification import classify_event_to_tier

    return classify_event_to_tier(event_type)


def is_catalog_event_client_wire_visible(
    event_type: str | None,
    event_meta: EventMeta | None = None,
) -> bool:
    """Return True if a catalog event dict may be included on the client wire."""
    if not event_type or not is_client_broadcast_event_type(event_type):
        return False
    tier = resolve_event_verbosity_tier(event_type, event_meta)
    if tier is None:
        return True
    return should_show(tier, _CLIENT_WIRE_VERBOSITY_CEILING)


def is_client_wire_visible(
    msg: dict[str, Any],
    event_meta: EventMeta | None = None,
) -> bool:
    """Return True if a daemon wire message may be delivered to WebSocket clients.

    Verbose catalog events (DETAILED/DEBUG/INTERNAL tiers) are never sent, even when
    the client subscribed with ``verbosity=debug`` or the daemon runs at DEBUG log level.
    """
    if not isinstance(msg, dict):
        return False
    top_type = msg.get("type")
    if isinstance(top_type, str) and top_type in _ALWAYS_CLIENT_WIRE_TOP_TYPES:
        return True
    wire_type = event_type_from_wire_message(msg)
    if not wire_type:
        return True
    if wire_type in _ALWAYS_CLIENT_WIRE_INNER_TYPES:
        return True
    return is_catalog_event_client_wire_visible(wire_type, event_meta)


def is_custom_stream_payload_client_visible(data: Any) -> bool:
    """Return True if a runner ``custom`` stream payload may leave the worker."""
    if not isinstance(data, dict):
        return False
    event_type = data.get("type")
    if not isinstance(event_type, str):
        return True
    if event_type in _ALWAYS_CLIENT_WIRE_INNER_TYPES:
        return True
    event_meta = None
    if event_type.startswith("soothe."):
        from soothe.core.events.catalog import REGISTRY

        event_meta = REGISTRY.get_meta(event_type)
    return is_catalog_event_client_wire_visible(event_type, event_meta)


def event_type_from_wire_message(msg: dict[str, Any]) -> str | None:
    """Extract catalog event type from a daemon wire message dict."""
    if not isinstance(msg, dict):
        return None
    msg_type = msg.get("type")
    if msg_type == "event" and isinstance(msg.get("data"), dict):
        inner = msg["data"]
        inner_type = inner.get("type")
        if isinstance(inner_type, str):
            return inner_type
    if isinstance(msg_type, str):
        return msg_type
    return None


_PROGRESS_TYPE_PREFIXES = (
    "soothe.cognition.",
    "soothe.subagent.",
    "soothe.stream.",
)
_PROGRESS_TOP_LEVEL_TYPES = frozenset(
    {
        "status",
        "replay_complete",
        "loop_reattached",
        "history_replay",
        "subscription_confirmed",
        "error",
    }
)


def is_progress_wire_event(msg: dict[str, Any]) -> bool:
    """Return True if a wire message should be delivered at ``wire_tier=progress``."""
    top = msg.get("type")
    if isinstance(top, str) and top in _PROGRESS_TOP_LEVEL_TYPES:
        return True
    if top == "event":
        catalog_type = event_type_from_wire_message(msg)
        if catalog_type is None:
            return True
        if not is_client_broadcast_event_type(catalog_type):
            return False
        return catalog_type.startswith(_PROGRESS_TYPE_PREFIXES) or catalog_type == (
            "tool_call_updates_batch"
        )
    if isinstance(top, str) and top == "tool_call_updates_batch":
        return True
    return False


__all__ = [
    "event_type_from_wire_message",
    "is_catalog_event_client_wire_visible",
    "is_client_broadcast_event_type",
    "is_client_wire_visible",
    "is_custom_stream_payload_client_visible",
    "is_progress_wire_event",
    "resolve_event_verbosity_tier",
]
