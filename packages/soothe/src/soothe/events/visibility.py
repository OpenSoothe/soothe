"""Single source of truth for daemon-to-client wire visibility.

This module owns every "may this frame reach a WebSocket client?" decision.
All daemon delivery stages funnel through the predicates below:

- ``soothe_daemon.server.SootheDaemon._broadcast`` — broadcast-time gate.
- ``soothe_daemon.session.manager`` sender — per-client tier filter.
- ``soothe_daemon.query.stream_delivery.StreamDeliveryCoalescer`` — early
  drop of invisible ``custom`` payloads.
- ``soothe_daemon.event.reattachment`` — history-replay filter on reattach.

## Why centralize

Visibility rules silently drop frames. A bug here is invisible until users
report "no output". The IG-435 regression (loop ``…81ec`` postmortem) shipped
because ``mode=messages`` envelopes were not enumerated as a wire shape;
they fell through to "unknown event type → DEBUG tier → suppress" and every
synthesized answer was dropped.

To prevent that class of regression, this module classifies each wire frame
into an explicit ``WireEnvelopeKind`` and dispatches on it. New wire shapes
MUST extend the enum and the dispatch table — there is no implicit fallback.
Unknown shapes fail loud (warning log + suppress) so that future schema
changes are caught immediately rather than silently dropping user payloads.

## Wire frame shapes (daemon → client)

1. **Control frames** — ``msg["type"]`` ∈ ``_ALWAYS_CLIENT_WIRE_TOP_TYPES``
   (``status``, ``error``, ``replay_complete``, ``loop_*_response`` …).
   Always visible.

2. **Catalog events** — ``{"type": "event", "mode": "custom",
   "data": {"type": "soothe.<domain>.<component>.<action>", ...}}``. Visible
   iff the catalog type is non-internal and its verbosity tier is at or
   below ``_CLIENT_WIRE_VERBOSITY_CEILING``.

3. **LangGraph message chunks** — ``{"type": "event", "mode": "messages",
   "data": [message_dict, metadata_dict]}``. Always visible. These carry
   the user-visible assistant text and tool I/O. Empty / redundant frames
   are dropped earlier by the coalescer.

4. **LangGraph updates** — ``{"type": "event", "mode": "updates", ...}``.
   Dropped earlier in the coalescer (only interrupts survive). If one
   reaches this layer it is treated as visible (delegated downstream).

5. **Unknown** — anything that doesn't match the above. Logged at WARNING
   on first observation per type and **suppressed**.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.core.verbosity import VerbosityTier, should_show
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH

if TYPE_CHECKING:
    from soothe.events import EventMeta

logger = logging.getLogger(__name__)

_INTERNAL_PREFIX = "soothe.internal."

# Catalog or wire event types always delivered inside ``type: event`` envelopes.
_ALWAYS_CLIENT_WIRE_INNER_TYPES = frozenset(
    {
        TOOL_CALL_UPDATES_BATCH,
        STREAM_TOOL_CALL_UPDATE,
        "stream_degraded",
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

# LangGraph stream modes that can appear under ``{"type": "event", "mode": ...}``.
_LANGGRAPH_MESSAGE_MODE = "messages"
_LANGGRAPH_UPDATES_MODE = "updates"
_LANGGRAPH_CUSTOM_MODE = "custom"


class WireEnvelopeKind(StrEnum):
    """Closed enumeration of wire frame shapes the daemon broadcasts.

    Adding a new wire shape REQUIRES extending this enum and updating
    ``classify_wire_envelope`` plus ``_decide_visibility``. Missing dispatch
    falls through to ``UNKNOWN`` which is logged and suppressed.
    """

    NOT_A_DICT = "not_a_dict"
    CONTROL = "control"
    EVENT_CATALOG = "event_catalog"
    EVENT_MESSAGES = "event_messages"
    EVENT_UPDATES = "event_updates"
    UNKNOWN = "unknown"


class WireVisibilityDecision(NamedTuple):
    """Result of a visibility check, with a short machine-readable reason.

    The public ``is_client_wire_visible`` API returns just the boolean for
    backwards compatibility; callers wanting diagnostics use
    ``decide_client_wire_visibility`` instead.
    """

    visible: bool
    kind: WireEnvelopeKind
    reason: str


# Throttle warnings for unknown envelope kinds (one warning per (kind, sample_key)
# pair survives for the daemon process lifetime).
_UNKNOWN_WARNED: set[tuple[str, str]] = set()


def classify_wire_envelope(msg: Any) -> WireEnvelopeKind:
    """Classify a daemon wire message dict into a ``WireEnvelopeKind``.

    Args:
        msg: A wire frame from ``SootheDaemon._broadcast`` or the session sender.

    Returns:
        The envelope kind. ``UNKNOWN`` for shapes the policy does not recognize;
        such frames are suppressed by ``is_client_wire_visible`` and a warning is
        emitted (throttled per shape).
    """
    if not isinstance(msg, dict):
        return WireEnvelopeKind.NOT_A_DICT
    top_type = msg.get("type")
    if isinstance(top_type, str) and top_type in _ALWAYS_CLIENT_WIRE_TOP_TYPES:
        return WireEnvelopeKind.CONTROL
    if top_type == "event":
        mode = msg.get("mode")
        if mode == _LANGGRAPH_MESSAGE_MODE:
            return WireEnvelopeKind.EVENT_MESSAGES
        if mode == _LANGGRAPH_UPDATES_MODE:
            return WireEnvelopeKind.EVENT_UPDATES
        # ``custom`` (or unset mode) with a catalog ``data.type``: catalog event.
        data = msg.get("data")
        if isinstance(data, dict) and isinstance(data.get("type"), str):
            return WireEnvelopeKind.EVENT_CATALOG
    return WireEnvelopeKind.UNKNOWN


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
        from .catalog import REGISTRY

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


def _decide_visibility(
    msg: dict[str, Any],
    event_meta: EventMeta | None,
) -> WireVisibilityDecision:
    """Dispatch on envelope kind and return a typed decision.

    This is the single place new wire shapes must be wired up.
    """
    kind = classify_wire_envelope(msg)

    if kind is WireEnvelopeKind.NOT_A_DICT:
        return WireVisibilityDecision(False, kind, "not-a-dict")

    if kind is WireEnvelopeKind.CONTROL:
        return WireVisibilityDecision(True, kind, "control-frame")

    if kind is WireEnvelopeKind.EVENT_MESSAGES:
        # LangGraph ``messages`` mode carries AIMessage / ToolMessage payloads;
        # the body IS the user-visible answer / tool I/O. The coalescer already
        # filters empty / redundant frames upstream.
        return WireVisibilityDecision(True, kind, "messages-mode")

    if kind is WireEnvelopeKind.EVENT_UPDATES:
        # Coalescer drops non-interrupt updates earlier. If we see one here it
        # is intentional (e.g. interrupt) and delegated downstream.
        return WireVisibilityDecision(True, kind, "updates-mode")

    if kind is WireEnvelopeKind.EVENT_CATALOG:
        wire_type = event_type_from_wire_message(msg) or ""
        if wire_type in _ALWAYS_CLIENT_WIRE_INNER_TYPES:
            return WireVisibilityDecision(True, kind, f"always-inner:{wire_type}")
        visible = is_catalog_event_client_wire_visible(wire_type, event_meta)
        return WireVisibilityDecision(
            visible,
            kind,
            f"catalog:{wire_type}:{'visible' if visible else 'suppressed'}",
        )

    # WireEnvelopeKind.UNKNOWN — fail loud (once per shape) and suppress.
    sample_key = f"{msg.get('type')!r}/{msg.get('mode')!r}"
    warn_key = (kind.value, sample_key)
    if warn_key not in _UNKNOWN_WARNED:
        _UNKNOWN_WARNED.add(warn_key)
        logger.warning(
            "Unknown daemon wire envelope shape suppressed (type=%s mode=%s). "
            "Update WireEnvelopeKind + _decide_visibility in "
            "soothe.events.visibility if this is a new wire shape.",
            msg.get("type"),
            msg.get("mode"),
        )
    return WireVisibilityDecision(False, kind, f"unknown:{sample_key}")


def decide_client_wire_visibility(
    msg: dict[str, Any],
    event_meta: EventMeta | None = None,
) -> WireVisibilityDecision:
    """Public diagnostic variant of ``is_client_wire_visible``.

    Returns the visibility decision with envelope kind and a short reason
    string, useful for daemon broadcast logging and tests. The boolean-only
    ``is_client_wire_visible`` remains for callers that don't need the reason.
    """
    return _decide_visibility(msg, event_meta)


def is_client_wire_visible(
    msg: dict[str, Any],
    event_meta: EventMeta | None = None,
) -> bool:
    """Return True if a daemon wire message may be delivered to WebSocket clients.

    Verbose catalog events (DETAILED/DEBUG/INTERNAL tiers) are never sent, even when
    the client subscribed with ``verbosity=debug`` or the daemon runs at DEBUG log
    level. ``messages``-mode envelopes (LangGraph AI/Tool payloads) are always
    visible — the coalescer is responsible for dropping empty / redundant frames.
    Unknown envelope shapes are suppressed and a warning is logged (once per shape).
    """
    return _decide_visibility(msg, event_meta).visible


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
        from .catalog import REGISTRY

        event_meta = REGISTRY.get_meta(event_type)
    return is_catalog_event_client_wire_visible(event_type, event_meta)


def event_type_from_wire_message(msg: dict[str, Any]) -> str | None:
    """Extract catalog event type from a daemon wire message dict.

    Only meaningful for ``EVENT_CATALOG``-kind envelopes; for ``EVENT_MESSAGES``
    and other shapes the inner ``data`` carries no catalog type and the
    function falls back to the outer ``msg["type"]`` (``"event"``). Callers
    that need to distinguish should use ``classify_wire_envelope`` instead.
    """
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
    "WireEnvelopeKind",
    "WireVisibilityDecision",
    "classify_wire_envelope",
    "decide_client_wire_visibility",
    "event_type_from_wire_message",
    "is_catalog_event_client_wire_visible",
    "is_client_broadcast_event_type",
    "is_client_wire_visible",
    "is_custom_stream_payload_client_visible",
    "is_progress_wire_event",
    "resolve_event_verbosity_tier",
]
