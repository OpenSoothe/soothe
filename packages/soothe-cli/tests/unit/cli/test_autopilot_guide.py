"""CLI tests for ``soothe autopilot guide`` (IG-733)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from soothe_cli.cli.main import app

runner = CliRunner()


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.commands.autopilot_cmd._require_daemon_ws",
        lambda: client,
    )
    return client


def test_guide_job_root(mock_client: MagicMock) -> None:
    mock_client.job_guidance.return_value = {
        "job_id": "abcd1234",
        "goal_id": "abcd1234",
        "absorbed": True,
    }
    result = runner.invoke(
        app,
        ["autopilot", "guide", "abcd1234", "Prefer feature branches"],
    )
    assert result.exit_code == 0, result.output
    mock_client.job_guidance.assert_called_once_with(
        "abcd1234",
        "Prefer feature branches",
        goal_id=None,
    )
    assert "Guidance absorbed" in result.output


def test_guide_with_goal(mock_client: MagicMock) -> None:
    mock_client.job_guidance.return_value = {
        "job_id": "abcd1234",
        "goal_id": "child001",
        "absorbed": True,
    }
    result = runner.invoke(
        app,
        ["autopilot", "guide", "abcd1234", "Fix login", "--goal", "child001"],
    )
    assert result.exit_code == 0, result.output
    mock_client.job_guidance.assert_called_once_with(
        "abcd1234",
        "Fix login",
        goal_id="child001",
    )


def test_guide_empty_text(mock_client: MagicMock) -> None:
    result = runner.invoke(app, ["autopilot", "guide", "abcd1234", "   "])
    assert result.exit_code != 0
    mock_client.job_guidance.assert_not_called()


def test_guide_not_absorbed(mock_client: MagicMock) -> None:
    mock_client.job_guidance.return_value = {
        "job_id": "abcd1234",
        "goal_id": "abcd1234",
        "absorbed": False,
    }
    result = runner.invoke(app, ["autopilot", "guide", "abcd1234", "hello"])
    assert result.exit_code != 0
    assert "not absorbed" in result.output.lower()
