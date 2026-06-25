"""Unit tests for soothe cron CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from typer.testing import CliRunner

from soothe_cli.cli.main import app


def _job_payload(job_id: str = "abc123def456") -> dict:
    return {
        "id": job_id,
        "description": "Check deploy",
        "schedule_kind": "delay",
        "schedule_value": "1h",
        "next_run": datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC).isoformat(),
        "status": "pending",
        "priority": 50,
        "run_count": 0,
    }


def test_cron_add_success(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.add.return_value = {"job": _job_payload()}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "add", "in 1 hour check deploy"])
    assert result.exit_code == 0
    assert "abc123def456" in result.output
    assert "Check deploy" in result.output
    mock_client.add.assert_called_once_with("in 1 hour check deploy", priority=None)


def test_cron_add_with_priority(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.add.return_value = {"job": _job_payload()}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(
        app,
        ["cron", "add", "every day at 9am standup", "--priority", "80"],
    )
    assert result.exit_code == 0
    mock_client.add.assert_called_once_with("every day at 9am standup", priority=80)


def test_cron_list_empty(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.list_jobs.return_value = {"jobs": []}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "list"])
    assert result.exit_code == 0
    assert "No scheduled jobs found" in result.output


def test_cron_list_with_jobs(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.list_jobs.return_value = {"jobs": [_job_payload()]}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "list", "--status", "pending"])
    assert result.exit_code == 0
    assert "abc123" in result.output
    mock_client.list_jobs.assert_called_once_with(status="pending")


def test_cron_show_job(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.show.return_value = {"job": _job_payload()}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "show", "abc123def456"])
    assert result.exit_code == 0
    assert "Check deploy" in result.output
    mock_client.show.assert_called_once_with("abc123def456")


def test_cron_show_missing_job(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.show.return_value = {"job": None}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "show", "missing"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cron_cancel_job(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.cancel.return_value = {"cancelled": True, "job_id": "abc123def456"}
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "cancel", "abc123def456"])
    assert result.exit_code == 0
    assert "Cancelled job" in result.output
    mock_client.cancel.assert_called_once_with("abc123def456")


def test_cron_http_error(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.add.side_effect = RuntimeError("HTTP 400 for /api/v1/cron/jobs: bad schedule")
    monkeypatch.setattr(
        "soothe_cli.cli.commands.cron_cmd._require_cron_client",
        lambda: mock_client,
    )

    result = CliRunner().invoke(app, ["cron", "add", "not a schedule"])
    assert result.exit_code == 1
    assert "HTTP 400" in result.output
