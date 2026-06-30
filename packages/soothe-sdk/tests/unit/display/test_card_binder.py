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


def test_convert_messages_to_data_empty_tool_name_falls_back_to_unknown() -> None:
    """Tool calls with missing/blank names must not break card binding."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "", "args": {"cmd": "ls"}}],
        ),
        ToolMessage(content="ok", tool_call_id="tc1", name="", status="success"),
    ]
    data = card_binder.convert_messages_to_data(messages)
    tools = [m for m in data if m.type == MessageType.TOOL]
    assert len(tools) == 1
    assert tools[0].tool_name == "unknown"
    assert tools[0].tool_status == ToolStatus.SUCCESS


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
            "type": "soothe.cognition.strange_loop.step.started",
            "step_id": "step_001",
            "description": "Read the file",
        },
    }
    completed = {
        "kind": "event",
        "timestamp": "2026-06-04T10:00:05+00:00",
        "data": {
            "type": "soothe.cognition.strange_loop.step.completed",
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
        {"kind": "event", "data": {"type": "soothe.cognition.strange_loop.started"}},
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


def test_collect_cognition_card_replay_surfaces_assistant_conversation_rows() -> None:
    """Resume must replay the persisted goal_completion / plan_direct text.

    For LEDGER_DIRECT goal completion, the final user-visible answer never
    reaches the checkpoint ledger (the goal_completion node skips appending),
    so it is persisted as a ``kind=conversation, role=assistant`` row instead.
    The cognition collector must surface it as an ASSISTANT card so the merge
    into the resumed transcript interleaves it with cognition/step cards.
    """
    events = [
        {
            "kind": "conversation",
            "role": "user",
            "text": "count all file types",
            "timestamp": "2026-06-04T10:00:00+00:00",
        },
        {
            "kind": "conversation",
            "role": "assistant",
            "text": "I will complete this goal directly: count all file types",
            "phase": "plan_direct",
            "timestamp": "2026-06-04T10:00:05+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:10+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.completed",
                "step_id": "NPT-01",
                "success": True,
                "duration_ms": 18806,
                "tool_call_count": 1,
                "summary": "Done [1 tools]",
            },
        },
        {
            "kind": "conversation",
            "role": "assistant",
            "text": "Result\n\n| Extension | Count | Description |\nTotal: 2480 files",
            "phase": "goal_completion",
            "timestamp": "2026-06-04T10:00:20+00:00",
        },
    ]
    cards = card_binder.collect_cognition_card_replay(events)

    types = [c.type for c in cards]
    assert MessageType.ASSISTANT in types, "plan_direct + goal_completion text must be replayed"
    assistants = [c for c in cards if c.type == MessageType.ASSISTANT]
    assert len(assistants) == 2
    assert assistants[0].content.startswith("I will complete this goal directly")
    assert "Total: 2480 files" in assistants[1].content
    # User conversation rows must NOT be replayed (they would duplicate the
    # checkpoint HumanMessage card emitted by convert_messages_to_data).
    assert not any(c.type == MessageType.USER for c in cards)


def test_collect_cognition_card_replay_dedups_duplicate_assistant_text() -> None:
    """Daemon may write the same goal_completion replay text more than once."""
    events = [
        {
            "kind": "conversation",
            "role": "assistant",
            "text": "Final answer",
            "phase": "goal_completion",
            "timestamp": "2026-06-04T10:00:00+00:00",
        },
        {
            "kind": "conversation",
            "role": "assistant",
            "text": "Final answer",
            "phase": "goal_completion",
            "timestamp": "2026-06-04T10:00:01+00:00",
        },
    ]
    cards = card_binder.collect_cognition_card_replay(events)
    assistants = [c for c in cards if c.type == MessageType.ASSISTANT]
    assert len(assistants) == 1


def test_convert_messages_to_data_suppresses_standalone_tool_when_cognition_replay_present() -> (
    None
):
    """With cognition cards in play, tool activity belongs in the STEP card.

    Live UX never renders a standalone ``[run_command]`` widget — the tool
    rows are aggregated into the active CognitionStepMessage. Resume must
    match: when ``cognition_card_replay`` is non-empty, hide the standalone
    TOOL cards that would otherwise be created from checkpoint tool_calls /
    ToolMessage pairs.
    """
    messages = [
        HumanMessage(content="count files"),
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "run_command", "args": {"command": "find ."}}],
        ),
        ToolMessage(
            content="output",
            tool_call_id="tc1",
            name="run_command",
            status="success",
        ),
    ]
    cognition = [
        MessageData(
            type=MessageType.STEP_PROGRESS,
            content="",
            step_progress_id="NPT-01",
            step_progress_description="count files",
            step_progress_phase="success",
            step_success=True,
            step_duration_ms=1000,
            step_tool_call_count=1,
            step_summary="Done [1 tools]",
        )
    ]
    cards = card_binder.convert_messages_to_data(messages, cognition_card_replay=cognition)
    assert not any(c.type == MessageType.TOOL for c in cards), (
        "standalone TOOL card must be suppressed when cognition_card_replay is provided"
    )
    # The step card itself must still be present
    assert any(c.type == MessageType.STEP_PROGRESS for c in cards)
    # And the user message
    assert any(c.type == MessageType.USER for c in cards)


def test_convert_event_to_message_data_drops_strange_loop_completed_app_banner() -> None:
    """Live TUI handles ``soothe.cognition.strange_loop.completed`` as a status
    transition (loop → "completed") not as a chat card. Resume must not
    synthesize a "Goal done · progress=complete" APP banner — the
    goal_completion text's own closing line is the natural endpoint marker.
    """
    event = {
        "kind": "event",
        "timestamp": "2026-06-04T10:00:00+00:00",
        "data": {
            "type": "soothe.cognition.strange_loop.completed",
            "status": "done",
            "goal_progress": "complete",
            "completion_summary": "Goal achieved successfully",
            "total_steps": 1,
        },
    }
    assert card_binder.convert_event_to_message_data(event) is None


def test_convert_messages_to_data_keeps_standalone_tool_when_no_cognition_replay() -> None:
    """Without cognition cards, the binder must still emit TOOL cards (back-compat)."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "run_command", "args": {}}],
        ),
        ToolMessage(content="ok", tool_call_id="tc1", name="run_command", status="success"),
    ]
    cards = card_binder.convert_messages_to_data(messages)
    tools = [c for c in cards if c.type == MessageType.TOOL]
    assert len(tools) == 1
    assert tools[0].tool_status == ToolStatus.SUCCESS


def test_build_step_tool_rows_map_binds_unified_id_to_step() -> None:
    """Stream tool_call.update events carry the unified id → step_id prefix.

    The map must group tool rows under the canonical (hyphen-form) step_id
    parsed from the unified id, populating args/output/duration from the
    interleaved ``tool_call`` / ``tool_result`` activity rows. This is what
    lets the resumed step card expand to inline rows instead of showing the
    bare ``N tools`` footer.
    """
    events = [
        {
            "kind": "tool_call",
            "tool_name": "ls",
            "args_preview": "{'path': '/tmp'}",
            "timestamp": "2026-06-04T10:00:00+00:00",
        },
        {
            "kind": "tool_result",
            "tool_name": "ls",
            "content": "['a', 'b']",
            "timestamp": "2026-06-04T10:00:00.050000+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:00.060000+00:00",
            "data": {
                "type": "soothe.stream.tool_call.update",
                "tool_call_id": "DPB_01:s:tool-abc123",
                "name": "ls",
                "args": {"path": "/tmp"},
            },
        },
        {
            "kind": "tool_call",
            "tool_name": "run_command",
            "args_preview": "{'command': 'pwd'}",
            "timestamp": "2026-06-04T10:00:01+00:00",
        },
        {
            "kind": "tool_result",
            "tool_name": "run_command",
            "content": "/tmp",
            "timestamp": "2026-06-04T10:00:01.100000+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:01.110000+00:00",
            "data": {
                "type": "soothe.stream.tool_call.update",
                "tool_call_id": "DPB_01:s:tool-def456",
                "name": "run_command",
                "args": {"command": "pwd"},
            },
        },
    ]
    rows_map = card_binder._build_step_tool_rows_map(events)
    assert list(rows_map.keys()) == ["DPB-01"]  # canonical hyphen form
    import json

    rows = json.loads(rows_map["DPB-01"])
    assert [r["name"] for r in rows] == ["ls", "run_command"]
    assert rows[0]["args"] == {"path": "/tmp"}
    assert rows[0]["output"] == "['a', 'b']"
    assert rows[0]["duration_ms"] == 50
    assert rows[0]["phase"] == "success"
    assert rows[0]["id"] == "DPB_01:s:tool-abc123"
    assert rows[1]["args"] == {"command": "pwd"}
    assert rows[1]["output"] == "/tmp"
    assert rows[1]["duration_ms"] == 100


def test_collect_cognition_card_replay_attaches_step_tool_calls_json() -> None:
    """STEP_PROGRESS cards from the cognition replay carry the inline tool rows."""
    events = [
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:00+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.started",
                "step_id": "DPB-01",
                "description": "do stuff",
            },
        },
        {
            "kind": "tool_call",
            "tool_name": "ls",
            "timestamp": "2026-06-04T10:00:01+00:00",
        },
        {
            "kind": "tool_result",
            "tool_name": "ls",
            "content": "['a']",
            "timestamp": "2026-06-04T10:00:01.050000+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:01.060000+00:00",
            "data": {
                "type": "soothe.stream.tool_call.update",
                "tool_call_id": "DPB_01:s:tool-1",
                "name": "ls",
                "args": {"path": "."},
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:02+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.completed",
                "step_id": "DPB-01",
                "success": True,
                "duration_ms": 2000,
                "tool_call_count": 1,
                "summary": "Done",
            },
        },
    ]
    cards = card_binder.collect_cognition_card_replay(events)
    step = next(c for c in cards if c.type == MessageType.STEP_PROGRESS)
    assert step.step_tool_calls_json is not None, "step card must carry inline tool rows"
    import json

    rows = json.loads(step.step_tool_calls_json)
    assert len(rows) == 1
    assert rows[0]["name"] == "ls"
    assert rows[0]["id"] == "DPB_01:s:tool-1"


def test_convert_loop_events_to_data_attaches_step_tool_calls_json_fallback_path() -> None:
    """Fallback path (no checkpoint messages) must also hydrate inline tool rows."""
    events = [
        {
            "kind": "conversation",
            "role": "user",
            "text": "go",
            "timestamp": "2026-06-04T10:00:00+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:01+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.started",
                "step_id": "NPT-01",
                "description": "do",
            },
        },
        {
            "kind": "tool_call",
            "tool_name": "run_command",
            "timestamp": "2026-06-04T10:00:02+00:00",
        },
        {
            "kind": "tool_result",
            "tool_name": "run_command",
            "content": "42",
            "timestamp": "2026-06-04T10:00:02.030000+00:00",
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:02.040000+00:00",
            "data": {
                "type": "soothe.stream.tool_call.update",
                "tool_call_id": "NPT_01:s:tool-z",
                "name": "run_command",
                "args": {"command": "echo 42"},
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-06-04T10:00:03+00:00",
            "data": {
                "type": "soothe.cognition.strange_loop.step.completed",
                "step_id": "NPT-01",
                "success": True,
                "duration_ms": 2000,
                "tool_call_count": 1,
                "summary": "Done",
            },
        },
    ]
    cards = card_binder.convert_loop_events_to_data(events)
    # Fallback must not emit standalone TOOL cards when cognition step events exist
    assert not any(c.type == MessageType.TOOL for c in cards)
    step = next(c for c in cards if c.type == MessageType.STEP_PROGRESS)
    assert step.step_tool_calls_json is not None
    import json

    rows = json.loads(step.step_tool_calls_json)
    assert len(rows) == 1
    assert rows[0]["name"] == "run_command"
    assert rows[0]["args"] == {"command": "echo 42"}
    assert rows[0]["output"] == "42"


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
