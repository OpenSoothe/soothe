"""SDK-level tests for the CardBinder (RFC-413).

These exercise the binder directly without instantiating ``SootheApp``,
proving the module runs as a pure transformation outside the TUI.
The TUI's existing ``test_convert_messages_to_data.py`` continues to cover
the same logic through the ``SootheApp._convert_messages_to_data`` delegate.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_sdk.display import card_binder
from soothe_sdk.display.transcript_types import MessageData, MessageType, ToolStatus


def test_convert_messages_to_data_user_assistant_pair() -> None:
    messages = [
        HumanMessage(content="hello"),
        AIMessage(content="hi there"),
    ]
    data = card_binder.convert_messages_to_data(messages)
    assert [m.type for m in data] == [MessageType.USER, MessageType.ASSISTANT]
    assert data[0].content == "hello"
    assert data[1].content == "hi there"


def test_convert_messages_to_data_matches_tool_call_to_result() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "/tmp/x"}}],
        ),
        ToolMessage(
            content="file contents",
            tool_call_id="tc1",
            name="read_file",
            status="success",
        ),
    ]
    data = card_binder.convert_messages_to_data(messages)
    tools = [m for m in data if m.type == MessageType.TOOL]
    assert len(tools) == 1
    assert tools[0].tool_status == ToolStatus.SUCCESS
    assert tools[0].tool_output == "file contents"
    assert tools[0].tool_args == {"path": "/tmp/x"}


def test_convert_messages_to_data_marks_unmatched_tool_call_rejected() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc_orphan", "name": "search", "args": {}}],
        ),
    ]
    data = card_binder.convert_messages_to_data(messages)
    tools = [m for m in data if m.type == MessageType.TOOL]
    assert len(tools) == 1
    assert tools[0].tool_status == ToolStatus.REJECTED


def test_convert_event_to_message_data_user_conversation_row() -> None:
    event = {
        "kind": "conversation",
        "role": "user",
        "content": "what's the weather",
        "timestamp": "2026-06-04T10:00:00+00:00",
    }
    msg = card_binder.convert_event_to_message_data(event)
    assert msg is not None
    assert msg.type == MessageType.USER
    assert msg.content == "what's the weather"


def test_convert_event_to_message_data_step_started_then_completed_merges() -> None:
    started = {
        "kind": "event",
        "timestamp": "2026-06-04T10:00:00+00:00",
        "data": {
            "type": "soothe.cognition.agent_loop.step.started",
            "step_id": "step_001",
            "description": "Read the file",
        },
    }
    completed = {
        "kind": "event",
        "timestamp": "2026-06-04T10:00:05+00:00",
        "data": {
            "type": "soothe.cognition.agent_loop.step.completed",
            "step_id": "step_001",
            "success": True,
            "duration_ms": 4210,
            "tool_call_count": 1,
            "summary": "Read 1 file",
        },
    }
    cards = card_binder.collect_cognition_card_replay([started, completed])
    assert len(cards) == 1
    card = cards[0]
    assert card.type == MessageType.STEP_PROGRESS
    assert card.step_progress_id == "step_001"
    assert card.step_progress_description == "Read the file"
    assert card.step_progress_phase == "success"
    assert card.step_success is True
    assert card.step_duration_ms == 4210
    assert card.step_tool_call_count == 1
    assert card.step_summary == "Read 1 file"


def test_is_loop_internal_checkpoint_message_recognizes_phase() -> None:
    msg = AIMessage(content="thinking out loud")
    msg.phase = "execute_step"
    assert card_binder.is_loop_internal_checkpoint_message(msg) is True

    public_msg = AIMessage(content="final answer")
    public_msg.phase = "goal_completion"
    assert card_binder.is_loop_internal_checkpoint_message(public_msg) is False


def test_merge_step_progress_prefers_later_metrics_keeps_description() -> None:
    prior = MessageData(
        type=MessageType.STEP_PROGRESS,
        content="",
        step_progress_id="s1",
        step_progress_description="Resolve config",
        step_progress_phase="running",
    )
    later = MessageData(
        type=MessageType.STEP_PROGRESS,
        content="",
        step_progress_id="s1",
        step_progress_description="(step)",  # placeholder
        step_progress_phase="success",
        step_success=True,
        step_duration_ms=1500,
        step_tool_call_count=2,
        step_summary="Done",
    )
    merged = card_binder.merge_step_progress(prior, later)
    assert merged.step_progress_description == "Resolve config"  # prior wins for description
    assert merged.step_progress_phase == "success"
    assert merged.step_success is True
    assert merged.step_duration_ms == 1500
    assert merged.step_summary == "Done"


def test_parse_loop_event_timestamp_returns_utc_aware() -> None:
    parsed = card_binder.parse_loop_event_timestamp("2026-06-04T10:00:00+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_loop_event_timestamp_returns_none_on_bad_input() -> None:
    assert card_binder.parse_loop_event_timestamp(None) is None
    assert card_binder.parse_loop_event_timestamp("not-a-timestamp") is None
    assert card_binder.parse_loop_event_timestamp(12345) is None


def test_conversation_rows_to_langchain_messages_filters_non_conversation() -> None:
    rows = [
        {"kind": "conversation", "role": "user", "content": "first"},
        {"kind": "event", "data": {"type": "soothe.cognition.agent_loop.started"}},
        {"kind": "conversation", "role": "assistant", "content": "answer"},
        {"kind": "tool_call", "tool_name": "read_file"},  # ignored
    ]
    messages = card_binder.conversation_rows_to_langchain_messages(rows)
    assert len(messages) == 2
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "first"
    assert isinstance(messages[1], AIMessage)
    assert messages[1].content == "answer"


def test_merge_visible_messages_with_cognition_cards_handles_empty_inputs() -> None:
    assert card_binder.merge_visible_messages_with_cognition_cards([], []) == []
    visible = [MessageData(type=MessageType.USER, content="x")]
    assert card_binder.merge_visible_messages_with_cognition_cards(visible, []) == visible
    cog = [
        MessageData(
            type=MessageType.COGNITION_REASON,
            content="",
            timestamp=1.0,
        )
    ]
    result = card_binder.merge_visible_messages_with_cognition_cards([], cog)
    assert result == cog


def test_module_has_no_textual_or_cli_imports() -> None:
    """Belt-and-suspenders: the binder must not pull in Textual or CLI code."""
    import soothe_sdk.display.card_binder as binder_module

    forbidden_prefixes = ("textual", "soothe_cli")
    for name in vars(binder_module):
        value = vars(binder_module)[name]
        module = getattr(value, "__module__", "")
        assert not any(module.startswith(p) for p in forbidden_prefixes), (
            f"Binder pulled in forbidden module via {name}: {module}"
        )


if __name__ == "__main__":  # pragma: no cover - convenience
    pytest.main([__file__, "-v"])
