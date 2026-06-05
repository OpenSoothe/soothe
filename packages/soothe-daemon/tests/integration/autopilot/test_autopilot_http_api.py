"""Integration tests for autopilot HTTP REST API endpoints.

Covers all /api/v1/autopilot/* routes with a real daemon and mocked
AutopilotService, verifying status codes, response shapes, and error handling.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)


class _FakeGoal:
    """Minimal Goal stand-in that supports `.model_dump(mode="json")`."""

    def __init__(
        self,
        goal_id: str = "goal0001",
        status: str = "pending",
        description: str = "Test goal",
        priority: int = 50,
    ) -> None:
        self.id = goal_id
        self.status = status
        self.description = description
        self.priority = priority
        self.error = None
        self.depends_on: list[str] = []
        self.assigned_loop_id: str | None = None

    def model_dump(self, *, mode: str = "python") -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "description": self.description,
            "priority": self.priority,
            "error": self.error,
            "depends_on": self.depends_on,
            "assigned_loop_id": self.assigned_loop_id,
        }


@pytest.fixture
async def daemon_with_http(tmp_path: Path):
    """Start a real daemon with HTTP REST enabled and mocked autopilot service."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
        http_port=port,
    )
    config.agent.autonomous = config.agent.autonomous.model_copy(update={"poll_interval": 2})

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    assert daemon._autopilot_service is not None

    svc = daemon._autopilot_service

    # Default mocks for all service methods
    default_goal = _FakeGoal()
    svc.status = MagicMock(
        return_value={
            "running": True,
            "dreaming": False,
            "loop_pool": {"active": 1, "idle": 2, "total": 3, "max": 5},
        }
    )
    svc.list_goals = AsyncMock(
        return_value=[
            _FakeGoal(goal_id="g1", status="active"),
            _FakeGoal(goal_id="g2", status="pending"),
        ]
    )
    svc.get_goal = AsyncMock(return_value=default_goal)
    svc.submit_task = AsyncMock(return_value=default_goal)
    svc.cancel_goal = AsyncMock(return_value=_FakeGoal(goal_id="goal0001", status="cancelled"))
    svc.approve_confirmation = AsyncMock(return_value=True)
    svc.reject_confirmation = AsyncMock(return_value=True)
    svc.wake_from_dreaming = AsyncMock()
    svc.force_dream = AsyncMock()

    await asyncio.sleep(0.3)

    try:
        yield {"daemon": daemon, "port": port}
    finally:
        await daemon.stop()


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


# ──────────────────────────────────────────────────────────
# GET /api/v1/autopilot/status
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_status(daemon_with_http) -> None:
    """GET /status returns state, running, dreaming, and loop_pool."""
    port = daemon_with_http["port"]

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/status"))
        assert resp.status == 200
        data = await resp.json()

        assert data["state"] == "active"
        assert data["running"] is True
        assert data["dreaming"] is False
        assert data["loop_pool"]["active"] == 1
        assert data["loop_pool"]["max"] == 5


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_status_dreaming(daemon_with_http) -> None:
    """GET /status reports dreaming state correctly."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    daemon._autopilot_service.status = MagicMock(
        return_value={
            "running": True,
            "dreaming": True,
            "loop_pool": {"active": 0, "idle": 3, "total": 3, "max": 5},
        }
    )

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/status"))
        assert resp.status == 200
        data = await resp.json()
        assert data["state"] == "dreaming"
        assert data["dreaming"] is True


# ──────────────────────────────────────────────────────────
# GET /api/v1/autopilot/goals
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_list_goals(daemon_with_http) -> None:
    """GET /goals returns serialized goal list."""
    port = daemon_with_http["port"]

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/goals"))
        assert resp.status == 200
        data = await resp.json()

        assert data["source"] == "autopilot_service"
        assert len(data["goals"]) == 2
        ids = {g["id"] for g in data["goals"]}
        assert ids == {"g1", "g2"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_list_goals_empty(daemon_with_http) -> None:
    """GET /goals returns empty list when no goals exist."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    daemon._autopilot_service.list_goals = AsyncMock(return_value=[])

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/goals"))
        assert resp.status == 200
        data = await resp.json()
        assert data["goals"] == []


# ──────────────────────────────────────────────────────────
# GET /api/v1/autopilot/goals/{goal_id}
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_get_goal(daemon_with_http) -> None:
    """GET /goals/{id} returns a single serialized goal."""
    port = daemon_with_http["port"]

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/goals/goal0001"))
        assert resp.status == 200
        data = await resp.json()

        assert data["source"] == "autopilot_service"
        assert data["goal"]["id"] == "goal0001"
        assert data["goal"]["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_get_goal_not_found(daemon_with_http) -> None:
    """GET /goals/{id} returns 404 when goal does not exist."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    daemon._autopilot_service.get_goal = AsyncMock(return_value=None)

    async with aiohttp.ClientSession() as session:
        resp = await session.get(_url(port, "/api/v1/autopilot/goals/nonexistent"))
        assert resp.status == 404


# ──────────────────────────────────────────────────────────
# POST /api/v1/autopilot/submit
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_submit(daemon_with_http) -> None:
    """POST /submit creates a new goal and returns goal_id."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "Build a widget", "priority": 80},
        )
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "submitted"
        assert data["goal_id"] == "goal0001"
        daemon._autopilot_service.submit_task.assert_awaited_once()
        call_kwargs = daemon._autopilot_service.submit_task.call_args
        assert call_kwargs[0][0] == "Build a widget"
        assert call_kwargs[1]["priority"] == 80


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_submit_missing_description(daemon_with_http) -> None:
    """POST /submit returns 400 when description is empty."""
    port = daemon_with_http["port"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"priority": 50},
        )
        assert resp.status == 400


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_submit_empty_description(daemon_with_http) -> None:
    """POST /submit returns 400 when description is an empty string."""
    port = daemon_with_http["port"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "", "priority": 50},
        )
        assert resp.status == 400


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_submit_default_priority(daemon_with_http) -> None:
    """POST /submit uses default priority 50 when omitted."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "No priority specified"},
        )
        assert resp.status == 200
        call_kwargs = daemon._autopilot_service.submit_task.call_args
        assert call_kwargs[1]["priority"] == 50


# ──────────────────────────────────────────────────────────
# DELETE /api/v1/autopilot/goals/{goal_id}
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_cancel_goal(daemon_with_http) -> None:
    """DELETE /goals/{id} cancels goal and returns new status."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.delete(_url(port, "/api/v1/autopilot/goals/goal0001"))
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "cancelled"
        assert data["goal_id"] == "goal0001"
        assert data["new_status"] == "cancelled"
        daemon._autopilot_service.cancel_goal.assert_awaited_once_with(
            "goal0001", reason="http_delete"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_cancel_goal_not_found(daemon_with_http) -> None:
    """DELETE /goals/{id} returns 404 when goal does not exist."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    daemon._autopilot_service.cancel_goal = AsyncMock(return_value=None)

    async with aiohttp.ClientSession() as session:
        resp = await session.delete(_url(port, "/api/v1/autopilot/goals/nonexistent"))
        assert resp.status == 404


# ──────────────────────────────────────────────────────────
# POST /api/v1/autopilot/goals/{goal_id}/approve
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_approve_goal(daemon_with_http) -> None:
    """POST /goals/{id}/approve approves a pending confirmation."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/goals/goal0001/approve"))
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "approved"
        assert data["goal_id"] == "goal0001"
        daemon._autopilot_service.approve_confirmation.assert_awaited_once_with("goal0001")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_approve_goal_not_found(daemon_with_http) -> None:
    """POST /goals/{id}/approve returns 404 when confirmation not found."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    daemon._autopilot_service.approve_confirmation = AsyncMock(return_value=False)

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/goals/nonexistent/approve"))
        assert resp.status == 404


# ──────────────────────────────────────────────────────────
# POST /api/v1/autopilot/goals/{goal_id}/reject
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_reject_goal(daemon_with_http) -> None:
    """POST /goals/{id}/reject rejects a proposed goal."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/goals/goal0001/reject"))
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "rejected"
        assert data["goal_id"] == "goal0001"
        daemon._autopilot_service.reject_confirmation.assert_awaited_once_with("goal0001")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_reject_goal_not_found(daemon_with_http) -> None:
    """POST /goals/{id}/reject returns 404 when confirmation not found."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    daemon._autopilot_service.reject_confirmation = AsyncMock(return_value=False)

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/goals/nonexistent/reject"))
        assert resp.status == 404


# ──────────────────────────────────────────────────────────
# POST /api/v1/autopilot/wake
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_wake(daemon_with_http) -> None:
    """POST /wake triggers exit from dreaming mode."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/wake"))
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "wake_sent"
        daemon._autopilot_service.wake_from_dreaming.assert_awaited_once_with(trigger="wake_signal")


# ──────────────────────────────────────────────────────────
# POST /api/v1/autopilot/dream
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_dream(daemon_with_http) -> None:
    """POST /dream forces entry into dreaming mode."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/dream"))
        assert resp.status == 200
        data = await resp.json()

        assert data["status"] == "dream_sent"
        daemon._autopilot_service.force_dream.assert_awaited_once()


# ──────────────────────────────────────────────────────────
# Service unavailable (503)
# ──────────────────────────────────────────────────────────


@pytest.fixture
async def daemon_without_autopilot(tmp_path: Path):
    """Start a daemon with HTTP but no autopilot service (set to None)."""
    force_isolated_home(tmp_path / "soothe-home-no-ap")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
        http_port=port,
    )
    config.agent.autonomous = config.agent.autonomous.model_copy(update={"poll_interval": 2})

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    # Null out autopilot service on the HTTP REST channel to simulate unavailable
    cm = daemon._channel_manager
    if "http_rest" in cm._channels:
        cm._channels["http_rest"]._autopilot_service = None

    await asyncio.sleep(0.3)

    try:
        yield {"daemon": daemon, "port": port}
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_503_when_service_unavailable(daemon_without_autopilot) -> None:
    """All autopilot endpoints return 503 when service is not initialized."""
    port = daemon_without_autopilot["port"]

    endpoints = [
        ("GET", "/api/v1/autopilot/status"),
        ("GET", "/api/v1/autopilot/goals"),
        ("GET", "/api/v1/autopilot/goals/any-id"),
        ("POST", "/api/v1/autopilot/submit"),
        ("DELETE", "/api/v1/autopilot/goals/any-id"),
        ("POST", "/api/v1/autopilot/goals/any-id/approve"),
        ("POST", "/api/v1/autopilot/goals/any-id/reject"),
        ("POST", "/api/v1/autopilot/wake"),
        ("POST", "/api/v1/autopilot/dream"),
    ]

    async with aiohttp.ClientSession() as session:
        for method, path in endpoints:
            kwargs: dict = {}
            if method == "POST" and "submit" in path:
                kwargs["json"] = {"description": "test"}

            req_fn = getattr(session, method.lower())
            resp = await req_fn(_url(port, path), **kwargs)
            assert resp.status == 503, f"{method} {path} should return 503"


# ──────────────────────────────────────────────────────────
# Lifecycle: submit → get → cancel
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_http_lifecycle(daemon_with_http) -> None:
    """Full HTTP lifecycle: submit → list → get → cancel → verify cancelled."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    svc = daemon._autopilot_service

    async with aiohttp.ClientSession() as session:
        # 1. Submit
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "Lifecycle test goal", "priority": 70},
        )
        assert resp.status == 200
        goal_id = (await resp.json())["goal_id"]

        # 2. List goals
        resp = await session.get(_url(port, "/api/v1/autopilot/goals"))
        assert resp.status == 200
        goals = (await resp.json())["goals"]
        assert len(goals) >= 1

        # 3. Get specific goal
        svc.get_goal = AsyncMock(
            return_value=_FakeGoal(
                goal_id=goal_id, status="active", description="Lifecycle test goal"
            )
        )
        resp = await session.get(_url(port, f"/api/v1/autopilot/goals/{goal_id}"))
        assert resp.status == 200
        goal_data = (await resp.json())["goal"]
        assert goal_data["status"] == "active"

        # 4. Cancel
        svc.cancel_goal = AsyncMock(return_value=_FakeGoal(goal_id=goal_id, status="cancelled"))
        resp = await session.delete(_url(port, f"/api/v1/autopilot/goals/{goal_id}"))
        assert resp.status == 200
        cancel_data = await resp.json()
        assert cancel_data["new_status"] == "cancelled"


# ──────────────────────────────────────────────────────────
# Lifecycle: submit → approve / reject
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_http_approve_reject_lifecycle(daemon_with_http) -> None:
    """Submit goal then approve, submit another then reject."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    svc = daemon._autopilot_service

    async with aiohttp.ClientSession() as session:
        # Submit and approve
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "Approve me"},
        )
        assert resp.status == 200
        gid = (await resp.json())["goal_id"]

        resp = await session.post(_url(port, f"/api/v1/autopilot/goals/{gid}/approve"))
        assert resp.status == 200
        assert (await resp.json())["status"] == "approved"

        # Submit and reject
        svc.submit_task = AsyncMock(
            return_value=_FakeGoal(goal_id="goal0002", description="Reject me")
        )
        resp = await session.post(
            _url(port, "/api/v1/autopilot/submit"),
            json={"description": "Reject me"},
        )
        assert resp.status == 200
        gid2 = (await resp.json())["goal_id"]

        resp = await session.post(_url(port, f"/api/v1/autopilot/goals/{gid2}/reject"))
        assert resp.status == 200
        assert (await resp.json())["status"] == "rejected"


# ──────────────────────────────────────────────────────────
# Wake / dream toggle
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_wake_dream_toggle(daemon_with_http) -> None:
    """Dream then wake — verify both calls reach the service."""
    port = daemon_with_http["port"]
    daemon = daemon_with_http["daemon"]
    svc = daemon._autopilot_service

    async with aiohttp.ClientSession() as session:
        resp = await session.post(_url(port, "/api/v1/autopilot/dream"))
        assert resp.status == 200
        svc.force_dream.assert_awaited_once()

        resp = await session.post(_url(port, "/api/v1/autopilot/wake"))
        assert resp.status == 200
        svc.wake_from_dreaming.assert_awaited_once()
