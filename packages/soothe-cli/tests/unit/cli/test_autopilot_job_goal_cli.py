"""CLI display enrichment for autopilot jobs/goals (rail_id and related fields)."""

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


def test_jobs_lists_rail(mock_client: MagicMock) -> None:
    mock_client.autopilot_list_jobs.return_value = {
        "jobs": [
            {
                "id": "abcd1234",
                "status": "active",
                "priority": 80,
                "description": "Ship feature",
                "total_tokens_used": 1200,
                "rail_id": "feature-dev",
            }
        ]
    }
    result = runner.invoke(app, ["autopilot", "jobs"])
    assert result.exit_code == 0, result.output
    assert "rail:feature-dev" in result.output
    assert "tok:" in result.output and "1K" in result.output
    assert "Ship feature" in result.output


def test_status_lists_job_rail(mock_client: MagicMock) -> None:
    mock_client.autopilot_status.return_value = {
        "state": "active",
        "running": True,
        "dreaming": False,
        "loop_pool": {"active": 1, "idle": 0, "max": 4},
    }
    mock_client.autopilot_list_jobs.return_value = {
        "jobs": [
            {
                "id": "jobroot01",
                "status": "pending",
                "description": "Root job",
                "total_tokens_used": 0,
                "rail_id": "greenfield-system",
            }
        ]
    }
    mock_client.autopilot_list_goals.return_value = {
        "goals": [
            {"id": "jobroot01", "status": "pending", "rail_id": "greenfield-system"},
            {"id": "child0001", "status": "active", "parent_id": "jobroot01"},
        ]
    }
    result = runner.invoke(app, ["autopilot", "status"])
    assert result.exit_code == 0, result.output
    assert "rail:greenfield-system" in result.output
    assert "Jobs (root goals): 1" in result.output


def test_job_detail_shows_rail(mock_client: MagicMock) -> None:
    mock_client.autopilot_get_job.return_value = {
        "job": {
            "id": "jobroot01",
            "status": "active",
            "priority": 50,
            "rail_id": "greenfield-system",
            "workspace": "/ws",
            "description": "Build system",
            "total_tokens_used": 5000,
            "created_at": "2026-08-07T01:00:00+00:00",
        },
        "dag": {
            "root_id": "jobroot01",
            "nodes": [
                {
                    "id": "jobroot01",
                    "status": "active",
                    "description": "Build system",
                    "rail_id": "greenfield-system",
                    "role": "root",
                },
                {
                    "id": "planner01",
                    "status": "active",
                    "description": "Plan modules",
                    "role": "planner",
                },
            ],
            "edges": [{"source": "jobroot01", "target": "planner01"}],
        },
        "active_goals": 2,
        "completed_goals": 0,
        "total_goals": 2,
        "total_tokens_used": 5000,
    }
    result = runner.invoke(app, ["autopilot", "job", "jobroot01"])
    assert result.exit_code == 0, result.output
    assert "Rail:            greenfield-system" in result.output
    assert 'jobroot0 (active) rail:greenfield-system role:root "Build system"' in result.output
    assert 'planner0 (active) role:planner "Plan modules"' in result.output


def test_goals_list_shows_rail_and_role(mock_client: MagicMock) -> None:
    mock_client.autopilot_list_goals.return_value = {
        "goals": [
            {
                "id": "jobroot01",
                "status": "active",
                "description": "Root",
                "rail_id": "spike",
                "role": "root",
            },
            {
                "id": "maker0001",
                "status": "pending",
                "parent_id": "jobroot01",
                "description": "Implement slice",
                "role": "maker",
            },
        ]
    }
    result = runner.invoke(app, ["autopilot", "goals"])
    assert result.exit_code == 0, result.output
    assert "rail:spike" in result.output
    assert "role:root" in result.output
    assert "parent:jobroot0" in result.output
    assert "role:maker" in result.output


def test_goal_detail_shows_rail_and_context(mock_client: MagicMock) -> None:
    mock_client.autopilot_get_goal.return_value = {
        "goal": {
            "id": "jobroot01",
            "description": "Spike the API",
            "status": "active",
            "priority": 60,
            "rail_id": "spike",
            "role": "root",
            "workspace": "/tmp/ws",
            "total_tokens_used": 2500,
            "depends_on": [],
            "assigned_loop_id": "autopilot__jobroot01__deadbeefdeadbeef",
            "created_at": "2026-08-07T02:00:00+00:00",
        }
    }
    result = runner.invoke(app, ["autopilot", "goal", "jobroot01"])
    assert result.exit_code == 0, result.output
    assert "Rail:        spike" in result.output
    assert "Role:        root" in result.output
    assert "Workspace:   /tmp/ws" in result.output
    assert "Tokens used: 2K" in result.output
    assert "Loop:" in result.output
