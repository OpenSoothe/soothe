"""Tests for autopilot submit/run CLI surface."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from soothe_cli.cli.main import app

runner = CliRunner()


def test_autopilot_help_is_concise() -> None:
    result = runner.invoke(app, ["autopilot", "--help"])
    assert result.exit_code == 0
    assert "Autopilot — autonomous goal control." in result.output
    assert "submit" in result.output
    assert "run" in result.output
    # Check for 'jobs' command presence (ANSI codes may split '│' from 'jobs' in CI)
    assert "jobs" in result.output
    assert "list" not in result.output  # 'list' was renamed to 'jobs'
    assert "``" not in result.output
    assert "max-iterations" not in result.output


def test_submit_help_documents_async_and_wait() -> None:
    result = runner.invoke(app, ["autopilot", "submit", "--help"])
    assert result.exit_code == 0
    # Check for async behavior mention (ANSI codes may split '--wait' in CI)
    assert "async" in result.output
    assert "wait" in result.output
    assert "--wait" in result.output
    assert "--no-wait" not in result.output
    assert "--workspace" in result.output or "-workspace" in result.output
    assert "-w" in result.output
    assert "max-iterations" not in result.output


def test_run_help_is_submit_wait_alias() -> None:
    result = runner.invoke(app, ["autopilot", "run", "--help"])
    assert result.exit_code == 0
    # Check for alias description (ANSI codes may split 'submit --wait' in CI)
    assert "submit" in result.output
    assert "wait" in result.output
    assert "sync" in result.output
    assert "max-iterations" not in result.output


def test_list_command_replaced_by_jobs(mock_autopilot_client: MagicMock) -> None:
    mock_autopilot_client.autopilot_list_jobs.return_value = {"jobs": []}
    gone = runner.invoke(app, ["autopilot", "list"])
    assert gone.exit_code != 0
    assert "No such command" in gone.output
    result = runner.invoke(app, ["autopilot", "jobs"])
    assert result.exit_code == 0, result.output
    assert "No jobs found." in result.output


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


def test_run_waits_like_submit_wait(mock_autopilot_client: MagicMock) -> None:
    result = runner.invoke(app, ["autopilot", "run", "do the thing", "-w", "/tmp/proj"])
    assert result.exit_code == 0, result.output
    kwargs: dict[str, Any] = mock_autopilot_client.autopilot_submit.call_args.kwargs
    assert kwargs.get("workspace") == "/tmp/proj"
    mock_autopilot_client.autopilot_get_goal.assert_called()


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
