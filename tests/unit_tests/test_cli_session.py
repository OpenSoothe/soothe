"""Tests for CLI session logging and review commands."""

from types import SimpleNamespace

from rich.console import Console

from soothe.cli.commands import handle_slash_command
from soothe.cli.session import InputHistory, SessionLogger


class DummyRunner:
    """Minimal runner stub for slash-command tests."""

    config = SimpleNamespace(policy_profile="standard", planner_routing="auto")

    def set_current_thread_id(self, thread_id):
        self.thread_id = thread_id


def test_session_logger_round_trips_conversation_and_events(tmp_path):
    """Session logs should retain both conversation turns and action events."""
    logger = SessionLogger(session_dir=str(tmp_path), thread_id="thread-1")

    logger.log_user_input("hello soothe")
    logger.log((), "custom", {"type": "soothe.session.started", "thread_id": "thread-1"})
    logger.log_assistant_response("hi there")

    records = logger.read_recent_records()

    assert [record["kind"] for record in records] == ["conversation", "event", "conversation"]
    assert [record["role"] for record in logger.recent_conversation()] == ["user", "assistant"]
    assert logger.recent_actions()[0]["data"]["type"] == "soothe.session.started"


def test_history_command_renders_recent_prompts(tmp_path):
    """The history command should show stored prompts."""
    history = InputHistory(history_file=str(tmp_path / "history.json"))
    history.add("first prompt")
    history.add("second prompt")
    console = Console(record=True, width=120)

    should_exit = handle_slash_command(
        "/history",
        DummyRunner(),
        console,
        input_history=history,
    )

    output = console.export_text()
    assert not should_exit
    assert "Recent Prompts" in output
    assert "second prompt" in output


def test_review_command_renders_conversation_and_actions(tmp_path):
    """The review command should surface both recent conversation and actions."""
    logger = SessionLogger(session_dir=str(tmp_path), thread_id="thread-2")
    logger.log_user_input("summarize the repo")
    logger.log((), "custom", {"type": "soothe.thread.created", "thread_id": "thread-2"})
    logger.log_assistant_response("Here is a short summary.")
    console = Console(record=True, width=120)

    should_exit = handle_slash_command(
        "/review",
        DummyRunner(),
        console,
        session_logger=logger,
    )

    output = console.export_text()
    assert not should_exit
    assert "Recent Conversation" in output
    assert "Recent Actions" in output
    assert "summarize the repo" in output
    assert "soothe.thread.created" in output
