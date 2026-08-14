"""Tests for autopilot submit/stop CLI surface."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from soothe_cli.cli.main import app

runner = CliRunner()

# ANSI escape sequence pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def test_autopilot_help_is_concise() -> None:
    result = runner.invoke(app, ["autopilot", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "Autopilot — autonomous goal control." in output
    assert "submit" in output
    assert "stop" in output
    assert re.search(r"\brun\b", output) is None
    assert re.search(r"\bcancel\b", output) is None
    # Check for 'jobs' command presence (ANSI codes may split '│' from 'jobs' in CI)
    assert "jobs" in output
    assert re.search(r"\blist\b", output) is None  # hidden alias of jobs
    assert "``" not in result.output
    assert "max-iterations" not in result.output


def test_submit_help_documents_async_and_wait() -> None:
    result = runner.invoke(app, ["autopilot", "submit", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    # Check for async behavior mention
    assert "async" in output
    assert "wait" in output
    assert "--wait" in output
    assert "--no-wait" not in output
    assert "--workspace" in output
    assert "-w" in output
    assert "--file" in output
    assert "-f" in output
    assert "TASK" in output or "task" in output.lower()
    assert "max-iterations" not in output


def test_run_command_removed() -> None:
    result = runner.invoke(app, ["autopilot", "run", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_cancel_command_removed() -> None:
    result = runner.invoke(app, ["autopilot", "cancel", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_list_is_alias_for_jobs(mock_autopilot_client: MagicMock) -> None:
    mock_autopilot_client.autopilot_list_jobs.return_value = {"jobs": []}
    via_list = runner.invoke(app, ["autopilot", "list"])
    assert via_list.exit_code == 0, via_list.output
    assert "No jobs found." in via_list.output
    via_jobs = runner.invoke(app, ["autopilot", "jobs"])
    assert via_jobs.exit_code == 0, via_jobs.output
    assert "No jobs found." in via_jobs.output
    assert mock_autopilot_client.autopilot_list_jobs.call_count == 2


@pytest.fixture
def mock_autopilot_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.autopilot_submit.return_value = {"goal_id": "abcdef12-3456", "rail_id": None}
    client.autopilot_get_goal.return_value = {
        "goal": {"id": "abcdef12-3456", "status": "completed"},
    }
    monkeypatch.setattr(
        "soothe_cli.cli.commands.autopilot_cmd._require_daemon_ws",
        lambda: client,
    )
    monkeypatch.setattr(
        "soothe_cli.cli.commands.autopilot_cmd._resolve_submit_workspace",
        lambda explicit: explicit or "/tmp/ws",
    )
    return client


def test_submit_is_async_by_default(mock_autopilot_client: MagicMock) -> None:
    result = runner.invoke(app, ["autopilot", "submit", "do the thing"])
    assert result.exit_code == 0, result.output
    mock_autopilot_client.autopilot_submit.assert_called_once()
    mock_autopilot_client.autopilot_get_goal.assert_not_called()
    assert "Submitted goal:" in result.output


def test_submit_wait_polls_until_done(mock_autopilot_client: MagicMock) -> None:
    result = runner.invoke(app, ["autopilot", "submit", "do the thing", "--wait"])
    assert result.exit_code == 0, result.output
    mock_autopilot_client.autopilot_submit.assert_called_once()
    mock_autopilot_client.autopilot_get_goal.assert_called()
    assert "completed" in result.output


def test_submit_passes_priority_and_rail(mock_autopilot_client: MagicMock) -> None:
    result = runner.invoke(
        app,
        [
            "autopilot",
            "submit",
            "task",
            "--priority",
            "80",
            "--rail",
            "feature-dev",
            "-w",
            "/ws",
        ],
    )
    assert result.exit_code == 0, result.output
    args, kwargs = mock_autopilot_client.autopilot_submit.call_args
    assert args[0] == "task"
    assert kwargs["priority"] == 80
    assert kwargs["rail_id"] == "feature-dev"
    assert kwargs["workspace"] == "/ws"


def test_submit_from_file(mock_autopilot_client: MagicMock, tmp_path) -> None:
    path = tmp_path / "job.md"
    path.write_text("Build the thing\n\nwith details\n", encoding="utf-8")
    result = runner.invoke(app, ["autopilot", "submit", "--file", str(path)])
    assert result.exit_code == 0, result.output
    args, _kwargs = mock_autopilot_client.autopilot_submit.call_args
    assert args[0] == "Build the thing\n\nwith details"


def test_submit_from_stdin(mock_autopilot_client: MagicMock) -> None:
    result = runner.invoke(
        app,
        ["autopilot", "submit", "-f", "-"],
        input="From stdin task\n",
    )
    assert result.exit_code == 0, result.output
    args, _kwargs = mock_autopilot_client.autopilot_submit.call_args
    assert args[0] == "From stdin task"


def test_stop_goal(mock_autopilot_client: MagicMock) -> None:
    mock_autopilot_client.autopilot_cancel_goal.return_value = {
        "goal_id": "abcdef12-3456",
        "new_status": "cancelled",
    }
    result = runner.invoke(app, ["autopilot", "stop", "abcdef12-3456"])
    assert result.exit_code == 0, result.output
    mock_autopilot_client.autopilot_cancel_goal.assert_called_once_with("abcdef12-3456")
    assert "Stop goal:" in result.output


def test_stop_all(mock_autopilot_client: MagicMock) -> None:
    mock_autopilot_client.autopilot_cancel_all.return_value = {"cancelled_count": 3}
    result = runner.invoke(app, ["autopilot", "stop", "--all"])
    assert result.exit_code == 0, result.output
    mock_autopilot_client.autopilot_cancel_all.assert_called_once()
    assert "Stopped 3 open goal(s)." in result.output


def test_stop_job(mock_autopilot_client: MagicMock) -> None:
    mock_autopilot_client.job_cancel.return_value = {"status": "cancelled"}
    result = runner.invoke(app, ["autopilot", "stop", "--job", "abcdef12-3456"])
    assert result.exit_code == 0, result.output
    mock_autopilot_client.job_cancel.assert_called_once_with("abcdef12-3456")
    assert "Stop job:" in result.output


def test_submit_without_task_or_file_errors(
    mock_autopilot_client: MagicMock,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare submit fails even when cwd has GOAL.md (IG-742)."""
    goal = tmp_path / "GOAL.md"
    goal.write_text("Should not be auto-loaded\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["autopilot", "submit"])
    assert result.exit_code == 1
    assert "Specify a task" in result.output
    mock_autopilot_client.autopilot_submit.assert_not_called()


def test_submit_rejects_task_and_file(mock_autopilot_client: MagicMock, tmp_path) -> None:
    path = tmp_path / "job.md"
    path.write_text("file task\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["autopilot", "submit", "inline task", "--file", str(path)],
    )
    assert result.exit_code == 1
    assert "exactly one of: TASK or --file" in result.output
    mock_autopilot_client.autopilot_submit.assert_not_called()


def test_submit_rejects_empty_file(mock_autopilot_client: MagicMock, tmp_path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("   \n", encoding="utf-8")
    result = runner.invoke(app, ["autopilot", "submit", "-f", str(path)])
    assert result.exit_code == 1
    assert "empty" in result.output.lower()
    mock_autopilot_client.autopilot_submit.assert_not_called()


def test_submit_rejects_missing_file(mock_autopilot_client: MagicMock, tmp_path) -> None:
    missing = tmp_path / "missing.md"
    result = runner.invoke(app, ["autopilot", "submit", "-f", str(missing)])
    assert result.exit_code == 1
    assert "Error reading task file" in result.output
    mock_autopilot_client.autopilot_submit.assert_not_called()
