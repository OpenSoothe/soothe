"""Tests for daemon-to-client wire visibility policy.

Every daemon delivery stage funnels through ``soothe.events.visibility``.
A regression here silently drops user-visible payloads (loop ``…81ec``
postmortem: synthesis and ledger-direct answers were dropped because the
``mode=messages`` envelope shape was not enumerated). This file maintains an
exhaustive matrix over ``WireEnvelopeKind`` so future schema changes are
forced to update the classifier and the dispatch table.
"""

from __future__ import annotations

import logging

import pytest
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH

from soothe.events import EventMeta
from soothe.events.visibility import (
    WireEnvelopeKind,
    classify_wire_envelope,
    decide_client_wire_visibility,
    event_type_from_wire_message,
    is_catalog_event_client_wire_visible,
    is_client_broadcast_event_type,
    is_client_wire_visible,
    is_custom_stream_payload_client_visible,
)

# ---------------------------------------------------------------------------
# is_client_broadcast_event_type / catalog tier
# ---------------------------------------------------------------------------


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
    assert is_client_broadcast_event_type("soothe.cognition.strange_loop.started") is True
    assert is_client_broadcast_event_type(None) is True


def test_verbose_catalog_events_not_client_wire_visible() -> None:
    assert is_catalog_event_client_wire_visible("soothe.lifecycle.loop.checkpoint_saved") is False
    assert is_catalog_event_client_wire_visible("soothe.cognition.strange_loop.started") is True


# ---------------------------------------------------------------------------
# event_type_from_wire_message (extractor)
# ---------------------------------------------------------------------------


def test_event_type_from_wire_message_custom() -> None:
    msg = {
        "type": "event",
        "mode": "custom",
        "data": {"type": "soothe.internal.memory.recalled", "count": 1},
    }
    assert event_type_from_wire_message(msg) == "soothe.internal.memory.recalled"


def test_event_type_from_wire_message_messages_falls_back_to_outer() -> None:
    """``messages``-mode data is a tuple/list; extractor returns outer ``event``."""
    msg = {
        "type": "event",
        "mode": "messages",
        "data": [{"type": "AIMessageChunk", "content": "x"}, {}],
    }
    assert event_type_from_wire_message(msg) == "event"


# ---------------------------------------------------------------------------
# classify_wire_envelope — exhaustive matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg,expected",
    [
        # not a dict
        ("not a dict", WireEnvelopeKind.NOT_A_DICT),
        (None, WireEnvelopeKind.NOT_A_DICT),
        # control frames
        ({"type": "status", "state": "running"}, WireEnvelopeKind.CONTROL),
        ({"type": "error", "message": "boom"}, WireEnvelopeKind.CONTROL),
        ({"type": "replay_complete"}, WireEnvelopeKind.CONTROL),
        ({"type": "loop_input_response"}, WireEnvelopeKind.CONTROL),
        ({"type": "event_batch", "events": []}, WireEnvelopeKind.CONTROL),
        # catalog event (mode=custom with data.type)
        (
            {
                "type": "event",
                "mode": "custom",
                "data": {"type": "soothe.cognition.step.started", "step_id": "X"},
            },
            WireEnvelopeKind.EVENT_CATALOG,
        ),
        # messages-mode (LangGraph AI/Tool payloads — list payload, no inner type)
        (
            {
                "type": "event",
                "mode": "messages",
                "data": [{"type": "AIMessageChunk", "content": "hi"}, {}],
            },
            WireEnvelopeKind.EVENT_MESSAGES,
        ),
        (
            {
                "type": "event",
                "mode": "messages",
                "data": (
                    {"type": "ToolMessage", "content": "out"},
                    {},
                ),
            },
            WireEnvelopeKind.EVENT_MESSAGES,
        ),
        # updates-mode (rare, usually dropped earlier)
        (
            {"type": "event", "mode": "updates", "data": {"__interrupt__": {}}},
            WireEnvelopeKind.EVENT_UPDATES,
        ),
        # unknown shapes
        ({"type": "weird_top_level"}, WireEnvelopeKind.UNKNOWN),
        ({"type": "event", "mode": "novel_mode", "data": {}}, WireEnvelopeKind.UNKNOWN),
        ({"type": "event"}, WireEnvelopeKind.UNKNOWN),
    ],
)
def test_classify_wire_envelope_matrix(msg: object, expected: WireEnvelopeKind) -> None:
    assert classify_wire_envelope(msg) is expected


# ---------------------------------------------------------------------------
# is_client_wire_visible — exhaustive matrix
# ---------------------------------------------------------------------------


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


def test_messages_mode_envelope_always_client_wire_visible() -> None:
    """``mode=messages`` envelopes (LangGraph AI/Tool message chunks) must reach clients.

    Regression guard: pre-fix, the catalog-tier path mis-classified these as
    ``DEBUG`` and dropped every assistant-text chunk (synthesis output,
    ledger-direct replay, execute-phase prose). See loop ``…81ec`` postmortem.
    """
    synthesis_chunk = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "messages",
        "data": [
            {
                "type": "AIMessageChunk",
                "content": "Final synthesis text...",
                "phase": "goal_completion",
            },
            {},
        ],
    }
    assert is_client_wire_visible(synthesis_chunk) is True

    tuple_payload_chunk = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "messages",
        "data": (
            {"type": "AIMessageChunk", "content": "hello", "phase": "execute_step"},
            {},
        ),
    }
    assert is_client_wire_visible(tuple_payload_chunk) is True

    tool_message_chunk = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "messages",
        "data": [
            {"type": "ToolMessage", "content": "tool output", "tool_call_id": "tc-1"},
            {},
        ],
    }
    assert is_client_wire_visible(tool_message_chunk) is True


def test_custom_mode_visibility_unchanged_by_messages_short_circuit() -> None:
    """Internal ``mode=custom`` payloads must still be suppressed after the fix."""
    internal_custom = {
        "type": "event",
        "loop_id": "loop-1",
        "namespace": [],
        "mode": "custom",
        "data": {"type": "soothe.internal.iteration.started", "iteration": 1},
    }
    assert is_client_wire_visible(internal_custom) is False


def test_internal_tier_catalog_event_not_client_wire_visible() -> None:
    class HeartbeatEvent(SootheEvent):
        type: str = "soothe.stream.heartbeat"

    event_meta = EventMeta(
        type_string="soothe.stream.heartbeat",
        model=HeartbeatEvent,
        domain="stream",
        component="heartbeat",
        action="tick",
        verbosity=VerbosityTier.INTERNAL,
    )
    msg = {
        "type": "event",
        "loop_id": "loop-1",
        "mode": "custom",
        "data": {"type": "soothe.stream.heartbeat"},
    }
    assert is_client_wire_visible(msg, event_meta=event_meta) is False


# ---------------------------------------------------------------------------
# Unknown-shape guardrail
# ---------------------------------------------------------------------------


def test_unknown_envelope_is_suppressed_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown wire shapes must NOT be silently delivered.

    They are suppressed (the safe default) AND logged at WARNING the first time
    a particular (type, mode) pair is observed, so a future schema change does
    not silently drop user payloads the way the IG-435 regression did.
    """
    # Use a unique shape so the throttle set does not already contain it.
    novel = {"type": "event", "mode": "future_mode_42", "data": {}}

    with caplog.at_level(logging.WARNING, logger="soothe.events.visibility"):
        assert is_client_wire_visible(novel) is False
        # Second call same shape — must NOT log again (throttle).
        assert is_client_wire_visible(novel) is False

    warning_records = [
        r for r in caplog.records if "Unknown daemon wire envelope shape" in r.getMessage()
    ]
    assert len(warning_records) == 1, (
        f"expected exactly one warning, got {len(warning_records)}: "
        f"{[r.getMessage() for r in warning_records]}"
    )


# ---------------------------------------------------------------------------
# decide_client_wire_visibility — diagnostic API
# ---------------------------------------------------------------------------


def test_decide_returns_decision_with_kind_and_reason() -> None:
    d = decide_client_wire_visibility({"type": "status", "state": "running"})
    assert d.visible is True
    assert d.kind is WireEnvelopeKind.CONTROL
    assert d.reason == "control-frame"

    d = decide_client_wire_visibility(
        {
            "type": "event",
            "mode": "messages",
            "data": [{"type": "AIMessageChunk", "content": "x"}, {}],
        }
    )
    assert d.visible is True
    assert d.kind is WireEnvelopeKind.EVENT_MESSAGES
    assert d.reason == "messages-mode"

    d = decide_client_wire_visibility(
        {
            "type": "event",
            "mode": "custom",
            "data": {"type": "soothe.internal.iteration.started"},
        }
    )
    assert d.visible is False
    assert d.kind is WireEnvelopeKind.EVENT_CATALOG
    assert "soothe.internal.iteration.started" in d.reason


def test_decide_not_a_dict_returns_suppress() -> None:
    d = decide_client_wire_visibility("nope")  # type: ignore[arg-type]
    assert d.visible is False
    assert d.kind is WireEnvelopeKind.NOT_A_DICT
