"""Tests for server-side event wire visibility."""

from __future__ import annotations

from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH

from soothe.core.events import EventMeta
from soothe.core.events.visibility import (
    event_type_from_wire_message,
    is_catalog_event_client_wire_visible,
    is_client_broadcast_event_type,
    is_client_wire_visible,
    is_custom_stream_payload_client_visible,
)


def test_internal_types_not_broadcast() -> None:
    assert is_client_broadcast_event_type("soothe.internal.iteration.started") is False


def test_internal_custom_stream_payload_not_visible() -> None:
    assert (
        is_custom_stream_payload_client_visible(
            {"type": "soothe.internal.iteration.started", "iteration": 1}
        )
        is False
    )
    assert is_custom_stream_payload_client_visible(
        {"type": TOOL_CALL_UPDATES_BATCH, "updates": [], "count": 0}
    )


def test_client_types_broadcast() -> None:
    assert is_client_broadcast_event_type("soothe.cognition.agent_loop.started") is True
    assert is_client_broadcast_event_type(None) is True


def test_event_type_from_wire_message_custom() -> None:
    msg = {
        "type": "event",
        "mode": "custom",
        "data": {"type": "soothe.internal.memory.recalled", "count": 1},
    }
    assert event_type_from_wire_message(msg) == "soothe.internal.memory.recalled"


def test_verbose_catalog_events_not_client_wire_visible() -> None:
    assert is_catalog_event_client_wire_visible("soothe.lifecycle.loop.checkpoint_saved") is False
    assert is_catalog_event_client_wire_visible("soothe.cognition.agent_loop.started") is True


def test_status_running_always_client_wire_visible() -> None:
    msg = {"type": "status", "state": "running", "loop_id": "loop-1"}
    assert is_client_wire_visible(msg) is True


def test_stream_tool_wire_events_client_visible_at_normal_verbosity() -> None:
    assert classify_event_to_tier(TOOL_CALL_UPDATES_BATCH) == VerbosityTier.NORMAL
    assert classify_event_to_tier(STREAM_TOOL_CALL_UPDATE) == VerbosityTier.NORMAL

    batch_msg = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "custom",
        "data": {
            "type": TOOL_CALL_UPDATES_BATCH,
            "updates": [
                {
                    "type": STREAM_TOOL_CALL_UPDATE,
                    "tool_call_id": "tc-1",
                    "name": "run_command",
                    "args": {"command": "ls"},
                }
            ],
        },
    }
    assert is_client_wire_visible(batch_msg) is True

    update_msg = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "custom",
        "data": {
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "tc-1",
            "name": "task",
            "args": {"description": "explore repo"},
        },
    }
    assert is_client_wire_visible(update_msg) is True


def test_debug_tier_catalog_event_not_client_wire_visible() -> None:
    class HeartbeatEvent(SootheEvent):
        type: str = "soothe.stream.heartbeat"

    event_meta = EventMeta(
        type_string="soothe.stream.heartbeat",
        model=HeartbeatEvent,
        domain="stream",
        component="heartbeat",
        action="tick",
        verbosity=VerbosityTier.DEBUG,
    )
    msg = {
        "type": "event",
        "loop_id": "loop-1",
        "data": {"type": "soothe.stream.heartbeat"},
    }
    assert is_client_wire_visible(msg, event_meta=event_meta) is False
