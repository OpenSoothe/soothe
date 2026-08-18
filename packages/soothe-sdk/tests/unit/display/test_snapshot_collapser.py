"""Unit tests for goal display snapshot collapsing (RFC-631)."""

from __future__ import annotations

from soothe_sdk.display.snapshot_collapser import (
    build_goal_snapshot,
    fold_display_cards,
    split_cards_by_user_segments,
)
from soothe_sdk.display.snapshot_types import GoalDisplaySnapshot
from soothe_sdk.display.transcript_types import MessageData, MessageType


def test_fold_display_cards_keeps_last_streaming_duplicate() -> None:
    cards = [
        MessageData(type=MessageType.ASSISTANT, content="hel", id="msg-a1", is_streaming=True),
        MessageData(type=MessageType.ASSISTANT, content="hello", id="msg-a1", is_streaming=False),
    ]
    folded = fold_display_cards(cards)
    assert len(folded) == 1
    assert folded[0].content == "hello"
    assert folded[0].is_streaming is False


def test_fold_display_cards_merges_unique_id_stream_fragments() -> None:
    cards = [
        MessageData(type=MessageType.USER, content="how are u", id="msg-u1"),
        MessageData(type=MessageType.ASSISTANT, content="Hello", id="msg-a1"),
        MessageData(type=MessageType.ASSISTANT, content="!", id="msg-a2"),
        MessageData(type=MessageType.ASSISTANT, content=" there", id="msg-a3"),
    ]
    folded = fold_display_cards(cards)
    assert len(folded) == 2
    assert folded[1].content == "Hello! there"


def test_build_goal_snapshot_injects_user_and_assistant() -> None:
    live = [
        MessageData(
            type=MessageType.TOOL,
            content="tool output",
            id="msg-t1",
            tool_name="search",
        ),
    ]
    snapshot = build_goal_snapshot(
        goal_id="loop_goal_0",
        goal_index=0,
        goal_text="Do the thing",
        status="completed",
        started_at="2026-07-05T00:00:00+00:00",
        completed_at="2026-07-05T00:01:00+00:00",
        duration_ms=60_000,
        tokens_used=42,
        goal_completion="Done.",
        live_cards=live,
    )
    assert isinstance(snapshot, GoalDisplaySnapshot)
    assert snapshot.goal_text == "Do the thing"
    assert snapshot.card_count == 3
    types = [c.type for c in snapshot.display_cards]
    assert types[0] == MessageType.USER
    assert types[-1] == MessageType.ASSISTANT
    assert snapshot.display_cards[-1].content == "Done."


def test_split_cards_by_user_segments() -> None:
    cards = [
        MessageData(type=MessageType.USER, content="first", id="msg-u1"),
        MessageData(type=MessageType.ASSISTANT, content="a1", id="msg-a1"),
        MessageData(type=MessageType.USER, content="second", id="msg-u2"),
        MessageData(type=MessageType.ASSISTANT, content="a2", id="msg-a2"),
    ]
    segments = split_cards_by_user_segments(cards)
    assert len(segments) == 2
    assert [c.content for c in segments[0]] == ["first", "a1"]
    assert [c.content for c in segments[1]] == ["second", "a2"]
