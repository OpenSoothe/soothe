"""Tests for card snapshot align/diff (RFC-413 Phase 4 / IG-655)."""

from __future__ import annotations

from soothe_sdk.display.card_ledger import (
    align_cards_preserving_ids,
    assign_card_stable_keys,
    diff_card_snapshots,
)
from soothe_sdk.display.transcript_types import MessageData, MessageType


def test_align_reuses_ids_for_stable_step_keys() -> None:
    prior = MessageData(
        type=MessageType.STEP_PROGRESS,
        content="",
        id="old-step",
        step_progress_id="S1",
        step_progress_phase="running",
    )
    newer = MessageData(
        type=MessageType.STEP_PROGRESS,
        content="",
        id="random-new",
        step_progress_id="S1",
        step_progress_phase="success",
        step_success=True,
        step_tool_call_count=3,
    )
    aligned, needs_replace = align_cards_preserving_ids([prior], [newer])
    assert needs_replace is False
    assert aligned[0].id == "old-step"
    assert aligned[0].step_tool_call_count == 3


def test_diff_emits_update_for_changed_updatable_fields() -> None:
    prior = MessageData(
        type=MessageType.ASSISTANT,
        content="hel",
        id="asst-1",
        is_streaming=True,
    )
    current = MessageData(
        type=MessageType.ASSISTANT,
        content="hello",
        id="asst-1",
        is_streaming=False,
    )
    mutations = diff_card_snapshots([prior], [current], start_seq=5)
    assert len(mutations) == 1
    assert mutations[0].op == "update"
    assert mutations[0].seq == 5
    assert mutations[0].data["content"] == "hello"
    assert mutations[0].data["is_streaming"] is False


def test_diff_emits_create_for_new_ids() -> None:
    current = MessageData(type=MessageType.USER, content="hi", id="u1")
    mutations = diff_card_snapshots([], [current], start_seq=1)
    assert len(mutations) == 1
    assert mutations[0].op == "create"
    assert mutations[0].card_id == "u1"


def test_align_requests_replace_when_card_removed() -> None:
    prior = [
        MessageData(type=MessageType.USER, content="a", id="u1"),
        MessageData(type=MessageType.ASSISTANT, content="b", id="a1"),
    ]
    newer = [MessageData(type=MessageType.USER, content="a", id="ignored")]
    _aligned, needs_replace = align_cards_preserving_ids(prior, newer)
    assert needs_replace is True


def test_assistant_ordinal_keys_stable_as_content_grows() -> None:
    first = MessageData(type=MessageType.ASSISTANT, content="h", loop_output_phase="plan_direct")
    second = MessageData(
        type=MessageType.ASSISTANT, content="hello", loop_output_phase="plan_direct"
    )
    assert assign_card_stable_keys([first]) == assign_card_stable_keys([second])
