"""Tests for checkpoint message conversion into MessageData."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_cli.tui.app import SootheApp
from soothe_cli.tui.widgets.message_store import MessageData, MessageType, ToolStatus


def test_convert_tool_message_respects_status_error_with_benign_content() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {}}],
        ),
        ToolMessage(
            content="ok",
            tool_call_id="tc1",
            name="read_file",
            status="error",
        ),
    ]
    data = SootheApp._convert_messages_to_data(messages)
    tool_msgs = [m for m in data if m.type == MessageType.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_status == ToolStatus.ERROR
    assert tool_msgs[0].tool_output == "ok"


def test_convert_tool_message_respects_arguments_json_string() -> None:
    """Loop replay: wire-style ``arguments`` must populate tool card args."""
    ai = AIMessage(content="", tool_calls=[])
    # LangChain rejects ``arguments`` at construct time; some checkpoints store it anyway.
    ai.tool_calls = [
        {"id": "tc-args", "name": "read_file", "arguments": '{"file_path": "/src/a.py"}'}
    ]
    messages = [
        ai,
        ToolMessage(
            content="ok",
            tool_call_id="tc-args",
            name="read_file",
            status="success",
        ),
    ]
    data = SootheApp._convert_messages_to_data(messages)
    tool_msgs = [m for m in data if m.type == MessageType.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_args == {"file_path": "/src/a.py"}


def test_convert_tool_message_list_content_uses_formatted_output() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc2", "name": "run", "args": {}}],
        ),
        ToolMessage(
            content=["line1", "line2"],
            tool_call_id="tc2",
            name="run",
            status="success",
        ),
    ]
    data = SootheApp._convert_messages_to_data(messages)
    tool_msgs = [m for m in data if m.type == MessageType.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_status == ToolStatus.SUCCESS
    assert tool_msgs[0].tool_output == "line1\nline2"


def test_merge_history_sources_handles_mixed_timestamp_awareness() -> None:
    """History merge should not crash on aware + naive datetime inputs."""
    app = object.__new__(SootheApp)
    checkpoint_messages = [AIMessage(content="hello")]
    activity_events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:26.946+00:00",
            "data": {"summary": "aware"},
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:27.100",
            "data": {"summary": "naive"},
        },
    ]

    merged = app._merge_history_sources(checkpoint_messages, activity_events)

    assert [source for source, _ in merged] == ["message", "event", "event"]


@pytest.mark.asyncio
async def test_fetch_loop_history_prefers_checkpoint_cards() -> None:
    """Resumed history should prioritize checkpoint conversion over event fallback."""
    app = object.__new__(SootheApp)
    app._get_loop_state_values = AsyncMock(
        return_value={
            "_context_tokens": 7,
            "messages": [HumanMessage(content="hello"), AIMessage(content="world")],
        }
    )
    app._fetch_loop_activity_events = AsyncMock(
        return_value=[
            {
                "kind": "tool_result",
                "content": "noisy fallback",
                "metadata": {"tool_name": "read_file"},
            }
        ]
    )

    payload = await app._fetch_loop_history_data("loop-1")

    assert payload.context_tokens == 7
    assert [m.type for m in payload.messages] == [MessageType.USER, MessageType.ASSISTANT]
    assert all("Tool result" not in m.content for m in payload.messages)
    app._fetch_loop_activity_events.assert_not_awaited()


def test_convert_loop_events_uses_metadata_for_tool_name_and_output() -> None:
    """Event fallback should build TOOL cards from metadata-rich rows."""
    app = object.__new__(SootheApp)
    events = [
        {
            "kind": "tool_call",
            "timestamp": "2026-04-20T15:41:26.946+00:00",
            "metadata": {
                "tool_name": "read_file",
                "args_preview": "{'file_path': '/tmp/a.py'}",
            },
        },
        {
            "kind": "tool_result",
            "timestamp": "2026-04-20T15:41:27.000+00:00",
            "content": "file body",
            "metadata": {"tool_name": "read_file"},
        },
    ]

    data = app._convert_loop_events_to_data(events)

    assert len(data) == 1
    assert data[0].type == MessageType.TOOL
    assert data[0].tool_name == "read_file"
    assert data[0].tool_status == ToolStatus.SUCCESS
    assert data[0].tool_output == "file body"


def test_resume_skips_internal_loop_checkpoint_when_cognition_replay_provided() -> None:
    """Loop continue should drop internal-phase AI/tools and inject cognition cards."""
    cognition = [
        MessageData(
            type=MessageType.COGNITION_REASON,
            content="",
            cognition_plan_next_action="Inspect outputs",
            cognition_plan_status="continue",
            cognition_plan_iteration=1,
            cognition_plan_action="keep",
            cognition_plan_assessment="",
            cognition_plan_strategy="",
            timestamp=1_000.0,
        )
    ]
    messages = [
        HumanMessage(content="Ship the fix"),
        AIMessage(
            content="calling tool",
            phase="execute_step",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {"file_path": "/a"}}],
        ),
        ToolMessage(content="data", tool_call_id="tc1", name="read_file"),
        AIMessage(content="All set.", phase="goal_completion"),
    ]
    data = SootheApp._convert_messages_to_data(
        messages,
        cognition_card_replay=cognition,
    )
    types = [m.type for m in data]
    assert MessageType.TOOL not in types
    assert MessageType.USER in types
    assert MessageType.ASSISTANT in types
    assert MessageType.COGNITION_REASON in types


def test_agent_loop_completed_event_yields_no_message_data() -> None:
    """Persisted completion event must not duplicate the goal-completion assistant line."""
    event = {
        "kind": "event",
        "timestamp": "2026-04-20T15:41:28.000+00:00",
        "metadata": {
            "data": {
                "type": "soothe.cognition.agent_loop.completed",
                "summary": "Goal done",
            }
        },
    }
    assert SootheApp._convert_event_to_message_data(event) is None


def test_convert_loop_events_maps_cognition_events_to_specialized_cards() -> None:
    """Cognition events should restore goal/plan/step cards, not app text."""
    app = object.__new__(SootheApp)
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.agent_loop.started",
                    "goal": "Implement feature X",
                    "max_iterations": 5,
                }
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:26.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.agent_loop.reasoned",
                    "next_action": "I will inspect tool outputs.",
                    "status": "continue",
                    "iteration": 2,
                    "plan_action": "keep",
                    "assessment_reasoning": "Current plan is effective.",
                    "plan_reasoning": "Keep plan and execute remaining steps.",
                }
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:27.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.agent_loop.step.started",
                    "step_id": "S_3",
                    "description": "Collect final evidence",
                }
            },
        },
    ]

    data = app._convert_loop_events_to_data(events)

    assert [m.type for m in data] == [
        MessageType.COGNITION_GOAL_TREE,
        MessageType.COGNITION_REASON,
        MessageType.STEP_PROGRESS,
    ]
    assert data[1].cognition_plan_next_action == "I will inspect tool outputs."
    assert data[2].step_progress_id == "S_3"
    assert data[2].step_progress_phase == "running"


@pytest.mark.asyncio
async def test_get_loop_state_values_recovers_messages_from_conversation_rows() -> None:
    """Resume should rehydrate empty checkpoint messages from persisted conversation rows."""
    app = object.__new__(SootheApp)
    daemon_session = SimpleNamespace()
    daemon_session.aget_loop_state = AsyncMock(return_value=SimpleNamespace(values={}))
    daemon_session.fetch_conversation_log = AsyncMock(
        return_value=[
            {"kind": "event", "content": "ignore"},
            {"kind": "conversation", "role": "user", "content": "Hello"},
            {
                "kind": "conversation",
                "metadata": {"role": "assistant", "text": "Hi, how can I help?"},
            },
        ]
    )
    daemon_session.aupdate_loop_state = AsyncMock()
    app._daemon_session = daemon_session

    values = await app._get_loop_state_values("loop-42")

    daemon_session.aget_loop_state.assert_awaited_once_with("loop-42")
    assert "messages" in values
    assert isinstance(values["messages"], list)
    assert len(values["messages"]) == 2
    assert isinstance(values["messages"][0], HumanMessage)
    assert isinstance(values["messages"][1], AIMessage)
    daemon_session.fetch_conversation_log.assert_awaited_once_with(
        "loop-42",
        limit=10000,
        include_events=True,
    )
    daemon_session.aupdate_loop_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_loop_state_values_skips_recovery_when_messages_exist() -> None:
    """Resume should not fetch conversation logs when checkpoint messages are already present."""
    app = object.__new__(SootheApp)
    daemon_session = SimpleNamespace()
    daemon_session.aget_loop_state = AsyncMock(
        return_value=SimpleNamespace(values={"messages": [HumanMessage(content="existing")]})
    )
    daemon_session.fetch_conversation_log = AsyncMock()
    daemon_session.aupdate_loop_state = AsyncMock()
    app._daemon_session = daemon_session

    values = await app._get_loop_state_values("loop-42")

    daemon_session.aget_loop_state.assert_awaited_once_with("loop-42")
    assert len(values["messages"]) == 1
    daemon_session.fetch_conversation_log.assert_not_awaited()
    daemon_session.aupdate_loop_state.assert_not_awaited()
