"""Tests for CLI thread logging and review commands."""

from types import SimpleNamespace

import pytest
from rich.console import Console

from soothe.logging import GlobalInputHistory, ThreadLogger
from soothe.ux.tui.commands import handle_slash_command


class DummyRunner:
    """Minimal runner stub for slash-command tests."""

    config = SimpleNamespace(policy_profile="standard", planner_routing="auto")

    def set_current_thread_id(self, thread_id) -> None:
        self.thread_id = thread_id


def test_thread_logger_round_trips_conversation_and_events(tmp_path) -> None:
    """Thread logs should retain both conversation turns and action events."""
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="thread-1")

    logger.log_user_input("hello soothe")
    logger.log((), "custom", {"type": "soothe.lifecycle.thread.started", "thread_id": "thread-1"})
    logger.log_assistant_response("hi there")

    records = logger.read_recent_records()

    assert [record["kind"] for record in records] == ["conversation", "event", "conversation"]
    assert [record["role"] for record in logger.recent_conversation()] == ["user", "assistant"]
    assert logger.recent_actions()[0]["data"]["type"] == "soothe.lifecycle.thread.started"


@pytest.mark.asyncio
async def test_history_command_renders_recent_prompts(tmp_path) -> None:
    """The history command should show stored prompts."""
    history = GlobalInputHistory(history_file=str(tmp_path / "history.jsonl"))
    history.add("first prompt", thread_id="test-thread")
    history.add("second prompt", thread_id="test-thread")
    console = Console(record=True, width=120)

    should_exit = await handle_slash_command(
        "/history",
        DummyRunner(),
        console,
        input_history=history,
    )

    output = console.export_text()
    assert not should_exit
    assert "Recent Prompts" in output
    assert "second prompt" in output


@pytest.mark.asyncio
async def test_review_command_renders_conversation_and_actions(tmp_path) -> None:
    """The review command should surface both recent conversation and actions."""
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="thread-2")
    logger.log_user_input("summarize the repo")
    logger.log((), "custom", {"type": "soothe.lifecycle.thread.created", "thread_id": "thread-2"})
    logger.log_assistant_response("Here is a short summary.")
    console = Console(record=True, width=120)

    should_exit = await handle_slash_command(
        "/review",
        DummyRunner(),
        console,
        thread_logger=logger,
    )

    output = console.export_text()
    assert not should_exit
    assert "Recent Conversation" in output
    assert "Recent Actions" in output
    assert "summarize the repo" in output
    assert "soothe.lifecycle.thread.created" in output
