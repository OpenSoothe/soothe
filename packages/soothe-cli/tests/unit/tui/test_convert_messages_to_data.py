"""Tests for checkpoint message conversion into MessageData."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_cli.tui.app import SootheApp
from soothe_cli.tui.app._history import _HistoryMixin
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
            "data": {
                "type": "soothe.cognition.strange_loop.step.started",
                "step_id": "s1",
                "description": "aware",
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:27.100",
            "data": {
                "type": "soothe.cognition.strange_loop.step.started",
                "step_id": "s2",
                "description": "naive",
            },
        },
    ]

    merged = app._merge_history_sources(checkpoint_messages, activity_events)

    assert [source for source, _ in merged] == ["message", "event", "event"]


# test_fetch_loop_history_prefers_checkpoint_cards was removed when RFC-413
# replaced the legacy checkpoint+activity-log fallback path. New ledger-RPC
# behavior is covered by ``test_fetch_loop_history_data_uses_ledger_rpc``
# (and the empty-payload tests) further down in this file.


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
            cognition_plan_status="continue",
            cognition_plan_iteration=1,
            cognition_plan_action="keep",
            cognition_plan_assessment="Inspect outputs",
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


def test_strange_loop_completed_event_is_dropped() -> None:
    """Completion event is a status transition, not a chat card.

    The goal_completion text (persisted as a conversation row) is the
    natural endpoint marker — surfacing a separate APP banner would be
    redundant with the resumed transcript.
    """
    event = {
        "kind": "event",
        "timestamp": "2026-04-20T15:41:28.000+00:00",
        "metadata": {
            "data": {
                "type": "soothe.cognition.strange_loop.completed",
                "status": "completed",
                "summary": "Goal done",
            }
        },
    }
    msg = SootheApp._convert_event_to_message_data(event)
    assert msg is None


def test_convert_loop_events_maps_cognition_events_to_specialized_cards() -> None:
    """Cognition events should restore goal/plan/step cards, not app text."""
    app = object.__new__(SootheApp)
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.started",
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
                    "type": "soothe.cognition.strange_loop.reasoned",
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
                    "type": "soothe.cognition.strange_loop.step.started",
                    "step_id": "S_3",
                    "description": "Collect final evidence",
                }
            },
        },
    ]

    data = app._convert_loop_events_to_data(events)

    # The goal-tree pin (📍) is intentionally suppressed on history replay.
    assert [m.type for m in data] == [
        MessageType.COGNITION_REASON,
        MessageType.STEP_PROGRESS,
    ]
    assert data[0].cognition_plan_assessment == "Current plan is effective."
    assert data[1].step_progress_id == "S_3"
    assert data[1].step_progress_phase == "running"


def test_convert_event_to_message_data_handles_conversation_user_row() -> None:
    """Fallback path must render persisted user text from `kind=conversation` rows."""
    event = {
        "kind": "conversation",
        "role": "user",
        "content": "translate to chinese",
        "timestamp": "2026-04-20T15:41:25.000+00:00",
    }
    msg = SootheApp._convert_event_to_message_data(event)
    assert msg is not None
    assert msg.type == MessageType.USER
    assert msg.content == "translate to chinese"


def test_convert_event_to_message_data_handles_conversation_assistant_via_metadata() -> None:
    """Assistant text can arrive via the metadata envelope (older daemon writers)."""
    event = {
        "kind": "conversation",
        "metadata": {"role": "assistant", "text": "Sure, here it is."},
        "timestamp": "2026-04-20T15:41:26.000+00:00",
    }
    msg = SootheApp._convert_event_to_message_data(event)
    assert msg is not None
    assert msg.type == MessageType.ASSISTANT
    assert msg.content == "Sure, here it is."


def test_collect_cognition_card_replay_dedupes_step_progress_pair() -> None:
    """Replay must merge step.started + step.completed into one card per step_id.

    Live mode mutates the same CognitionStepMessage widget in place (see
    textual_adapter.py:`STRANGE_LOOP_STEP_COMPLETED`). Two separate cards on
    replay leave the started card stuck at "Running..." while a duplicate
    "(step) Completed" card appears next to it. The merge must also keep
    the description from ``step.started`` — the
    ``StrangeLoopStepCompletedEvent`` schema does not include ``description``.
    """
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.step.started",
                    "step_id": "S_1",
                    "description": "Scan project directory",
                }
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:30.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.step.completed",
                    "step_id": "S_1",
                    # NOTE: no `description` here, mirroring the production schema.
                    "success": True,
                    "duration_ms": 5000,
                    "tool_call_count": 3,
                    "summary": "Found 70k files",
                }
            },
        },
    ]
    cards = _HistoryMixin._collect_cognition_card_replay(events)
    step_cards = [c for c in cards if c.type == MessageType.STEP_PROGRESS]
    assert len(step_cards) == 1
    assert step_cards[0].step_progress_id == "S_1"
    assert step_cards[0].step_progress_description == "Scan project directory"
    assert step_cards[0].step_progress_phase == "success"
    assert step_cards[0].step_duration_ms == 5000
    assert step_cards[0].step_tool_call_count == 3
    assert step_cards[0].step_summary == "Found 70k files"


def test_collect_cognition_card_replay_drops_goal_tree_pin() -> None:
    """Goal-tree pin (📍 goal · iter<=N) must not render on resume."""
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:20.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.started",
                    "goal": "count all file types",
                    "max_iterations": 99,
                }
            },
        }
    ]
    cards = _HistoryMixin._collect_cognition_card_replay(events)
    assert not any(c.type == MessageType.COGNITION_GOAL_TREE for c in cards)


def test_convert_event_drops_completion_with_metadata() -> None:
    """strange_loop.completed is dropped even when metadata carries rich fields."""
    event = {
        "kind": "event",
        "timestamp": "2026-04-20T15:43:00.000+00:00",
        "metadata": {
            "data": {
                "type": "soothe.cognition.strange_loop.completed",
                "status": "completed",
                "goal_progress": "complete",
                "total_steps": 3,
                "goal": "count all file types",
                "completion_summary": "Counted 70,609 files across 80 extensions.",
                "evidence_summary": "",
            }
        },
    }
    msg = SootheApp._convert_event_to_message_data(event)
    assert msg is None


def test_collect_cognition_card_replay_keeps_started_when_completed_missing() -> None:
    """If only step.started is persisted (loop crashed mid-step), keep the running card."""
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.step.started",
                    "step_id": "S_orphan",
                    "description": "Half-finished work",
                }
            },
        },
    ]
    cards = _HistoryMixin._collect_cognition_card_replay(events)
    assert len(cards) == 1
    assert cards[0].step_progress_id == "S_orphan"
    assert cards[0].step_progress_phase == "running"


def test_convert_loop_events_dedupes_step_progress_pair() -> None:
    """Fallback path also merges step.started + step.completed into one card."""
    app = object.__new__(SootheApp)
    events = [
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.step.started",
                    "step_id": "S_2",
                    "description": "Aggregate counts",
                }
            },
        },
        {
            "kind": "event",
            "timestamp": "2026-04-20T15:41:32.000+00:00",
            "metadata": {
                "data": {
                    "type": "soothe.cognition.strange_loop.step.completed",
                    "step_id": "S_2",
                    "description": "Aggregate counts",
                    "success": True,
                    "duration_ms": 7000,
                    "tool_call_count": 1,
                }
            },
        },
    ]
    data = app._convert_loop_events_to_data(events)
    step_cards = [c for c in data if c.type == MessageType.STEP_PROGRESS]
    assert len(step_cards) == 1
    assert step_cards[0].step_progress_phase == "success"
    assert step_cards[0].step_duration_ms == 7000


def test_convert_loop_events_renders_interleaved_conversation_rows() -> None:
    """Fallback rendering should include user/assistant bubbles next to tool cards."""
    app = object.__new__(SootheApp)
    events = [
        {
            "kind": "conversation",
            "role": "user",
            "content": "find the bug",
            "timestamp": "2026-04-20T15:41:25.000+00:00",
        },
        {
            "kind": "tool_call",
            "timestamp": "2026-04-20T15:41:26.000+00:00",
            "metadata": {"tool_name": "grep", "args_preview": "{'pattern': 'TODO'}"},
        },
        {
            "kind": "tool_result",
            "timestamp": "2026-04-20T15:41:27.000+00:00",
            "content": "no matches",
            "metadata": {"tool_name": "grep"},
        },
        {
            "kind": "conversation",
            "role": "assistant",
            "content": "All clean.",
            "timestamp": "2026-04-20T15:41:28.000+00:00",
        },
    ]

    data = app._convert_loop_events_to_data(events)

    assert [m.type for m in data] == [
        MessageType.USER,
        MessageType.TOOL,
        MessageType.ASSISTANT,
    ]
    assert data[0].content == "find the bug"
    assert data[1].tool_status == ToolStatus.SUCCESS
    assert data[2].content == "All clean."


# Tests for ``_get_loop_state_values`` / ``_recover_missing_checkpoint_messages``
# were removed when RFC-413 made the daemon authoritative — those helpers
# are gone (the daemon owns derivation; the TUI reads cards via
# ``loop_cards_fetch``). The recovery-from-conversation-log behavior is now
# covered server-side in
# ``soothe-daemon/tests/unit/display/test_loop_card_manager.py``.


@pytest.mark.asyncio
async def test_fetch_loop_history_data_uses_ledger_rpc() -> None:
    """RFC-413: ``_fetch_loop_history_data`` is the single ledger path."""
    from soothe_sdk.display.card_ledger import card_to_wire_dict
    from soothe_sdk.display.transcript_types import MessageData, MessageType

    cards = [
        MessageData(type=MessageType.USER, content="hi"),
        MessageData(type=MessageType.ASSISTANT, content="hello"),
    ]
    wire_cards = [card_to_wire_dict(c) for c in cards]

    app = object.__new__(SootheApp)
    daemon_session = SimpleNamespace()
    daemon_session.fetch_loop_cards = AsyncMock(
        return_value=SimpleNamespace(
            cards=wire_cards,
            seq=2,
            context_tokens=512,
            success=True,
        )
    )
    app._daemon_session = daemon_session

    payload = await app._fetch_loop_history_data("loop-1")

    assert [m.content for m in payload.messages] == ["hi", "hello"]
    assert payload.context_tokens == 512


@pytest.mark.asyncio
async def test_fetch_loop_history_data_prefers_loop_history_fetch() -> None:
    """RFC-631: prefer goal snapshots + live tail over legacy card fetch."""
    from soothe_sdk.display.card_ledger import card_to_wire_dict
    from soothe_sdk.display.transcript_types import MessageData, MessageType

    frozen = [
        MessageData(type=MessageType.USER, content="goal 1", id="msg-u1"),
        MessageData(type=MessageType.ASSISTANT, content="done 1", id="msg-a1"),
    ]
    live = [
        MessageData(type=MessageType.USER, content="goal 2", id="msg-u2"),
    ]
    goal_dict = {
        "goal_id": "loop_goal_0",
        "goal_index": 0,
        "goal_text": "goal 1",
        "status": "completed",
        "display_cards": [card_to_wire_dict(c) for c in frozen],
        "card_count": 2,
        "goal_completion": "done 1",
    }

    app = object.__new__(SootheApp)
    daemon_session = SimpleNamespace()
    daemon_session.fetch_loop_history = AsyncMock(
        return_value=SimpleNamespace(
            goals=[goal_dict],
            live_cards=[card_to_wire_dict(c) for c in live],
            live_goal_index=1,
            context_tokens=128,
            success=True,
        )
    )
    daemon_session.fetch_loop_cards = AsyncMock(
        side_effect=AssertionError("legacy fetch should not run")
    )
    app._daemon_session = daemon_session

    payload = await app._fetch_loop_history_data("loop-631")

    assert [m.content for m in payload.messages] == ["goal 1", "done 1", "goal 2"]
    assert payload.context_tokens == 128
    assert payload.goals == (goal_dict,)


@pytest.mark.asyncio
async def test_fetch_loop_history_data_returns_empty_on_rpc_error() -> None:
    """When the ledger RPC raises, render an empty payload instead of crashing."""
    app = object.__new__(SootheApp)
    daemon_session = SimpleNamespace()
    daemon_session.fetch_loop_cards = AsyncMock(side_effect=RuntimeError("boom"))
    app._daemon_session = daemon_session

    payload = await app._fetch_loop_history_data("loop-2")

    assert payload.messages == []
    assert payload.context_tokens == 0


@pytest.mark.asyncio
async def test_fetch_loop_history_data_returns_empty_without_session() -> None:
    """Belt-and-suspenders: no daemon session ⇒ empty payload, no crash."""
    app = object.__new__(SootheApp)
    app._daemon_session = None

    payload = await app._fetch_loop_history_data("loop-3")

    assert payload.messages == []
    assert payload.context_tokens == 0
