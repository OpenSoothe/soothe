"""Unit tests for shared autopilot action dispatch."""

from __future__ import annotations

from typing import Any

import pytest

from soothe_daemon.protocol.autopilot_commands import run_autopilot_action
from soothe_daemon.protocol.schemas import PARAMS_REGISTRY


class _FakeGoal:
    def __init__(self, id: str, status: str = "active", parent_id: str | None = None) -> None:
        self.id = id
        self.status = status
        self.parent_id = parent_id

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "parent_id": self.parent_id}


class _FakeService:
    def __init__(self) -> None:
        self.last_include_terminal: bool | None = None

    def status(self) -> dict[str, Any]:
        return {"running": True, "dreaming": False, "loop_pool": {}}

    async def list_goals(self) -> list[_FakeGoal]:
        return [_FakeGoal("g1"), _FakeGoal("g2", parent_id="g1")]

    async def submit_task(
        self, description: str, *, priority: int = 50, workspace: str | None = None
    ) -> _FakeGoal:
        assert description
        return _FakeGoal("new-goal")

    async def top_snapshot(self, *, include_terminal: bool = False) -> dict[str, Any]:
        self.last_include_terminal = include_terminal
        return {
            "running": True,
            "dreaming": False,
            "loop_pool": {"active": 0, "idle": 0, "total": 0, "max": 4},
            "generated_at": "2026-08-04T00:00:00+00:00",
            "jobs": [],
        }


@pytest.mark.asyncio
async def test_run_autopilot_status() -> None:
    result = await run_autopilot_action(_FakeService(), "status", {})
    assert result["running"] is True
    assert result["state"] == "active"


@pytest.mark.asyncio
async def test_run_autopilot_list_jobs_roots_only() -> None:
    result = await run_autopilot_action(_FakeService(), "list_jobs", {})
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["id"] == "g1"


@pytest.mark.asyncio
async def test_run_autopilot_list_jobs_subtree_tokens() -> None:
    class _TokenService(_FakeService):
        async def subtree_total_tokens(self, root_goal_id: str) -> int:
            assert root_goal_id == "g1"
            return 4200

    result = await run_autopilot_action(_TokenService(), "list_jobs", {})
    assert result["jobs"][0]["total_tokens_used"] == 4200


@pytest.mark.asyncio
async def test_run_autopilot_submit_requires_description() -> None:
    with pytest.raises(RuntimeError, match="description"):
        await run_autopilot_action(_FakeService(), "submit", {})


@pytest.mark.asyncio
async def test_run_autopilot_top() -> None:
    svc = _FakeService()
    result = await run_autopilot_action(svc, "top", {})
    assert result["running"] is True
    assert result["jobs"] == []
    assert "generated_at" in result
    assert svc.last_include_terminal is False


@pytest.mark.asyncio
async def test_run_autopilot_top_include_terminal() -> None:
    svc = _FakeService()
    await run_autopilot_action(svc, "top", {"include_terminal": True})
    assert svc.last_include_terminal is True


def test_autopilot_status_registered_in_params_registry() -> None:
    assert ("request", "autopilot_status") in PARAMS_REGISTRY
    assert ("request", "autopilot_submit") in PARAMS_REGISTRY
    assert ("request", "autopilot_top") in PARAMS_REGISTRY
    model = PARAMS_REGISTRY[("request", "autopilot_status")]
    assert model.model_validate({}) is not None
    top_model = PARAMS_REGISTRY[("request", "autopilot_top")]
    assert top_model.model_validate({}) is not None
    assert top_model.model_validate({"include_terminal": True}).include_terminal is True
