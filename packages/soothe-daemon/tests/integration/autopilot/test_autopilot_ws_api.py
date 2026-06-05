"""Integration tests for autopilot WebSocket API error paths and edge cases.

Complements test_rfc228_ws_flow.py (happy paths) with error codes,
edge-case validation, concurrent clients, and service-unavailable scenarios.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import websockets

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)


async def _drain_handshake(ws) -> None:
    """Consume the two handshake messages (status + daemon_ready) sent on connect."""
    for _ in range(2):
        await asyncio.wait_for(ws.recv(), timeout=5.0)


async def _send_recv(ws, msg: dict) -> dict:
    """Send a JSON message and return the parsed response."""
    await ws.send(json.dumps(msg))
    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


class _FakeGoal:
    """Minimal Goal stand-in for mock returns."""

    def __init__(
        self,
        goal_id: str = "abc12345",
        status: str = "pending",
        description: str = "Integration test goal",
        priority: int = 50,
    ) -> None:
        self.id = goal_id
        self.status = status
        self.description = description
        self.priority = priority
        self.error = None
        self.depends_on: list[str] = []
        self.assigned_loop_id: str | None = None


@pytest.fixture
async def ws_daemon(tmp_path: Path):
    """Daemon with WebSocket transport and mocked autopilot service."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
        http_port=port + 1,
    )
    config.agent.autonomous = config.agent.autonomous.model_copy(update={"poll_interval": 2})

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    assert daemon._autopilot_service is not None

    svc = daemon._autopilot_service
    test_goal = _FakeGoal()

    # Default mocks
    svc.submit_task = AsyncMock(return_value=test_goal)
    svc.get_goal = AsyncMock(return_value=test_goal)
    svc.cancel_goal = AsyncMock(return_value=_FakeGoal(status="cancelled"))
    svc.list_goals = AsyncMock(return_value=[test_goal])
    svc.dag_snapshot = AsyncMock(
        return_value={
            "nodes": [
                {"id": "abc12345", "status": "pending", "description": "Root"},
            ],
            "edges": [],
        }
    )

    ge = svc._goal_engine
    ge.get_goal = AsyncMock(return_value=test_goal)
    ge.suspend_goal = AsyncMock(return_value=_FakeGoal(status="suspended"))
    ge.reactivate_goal = AsyncMock(return_value=_FakeGoal(status="pending"))
    ge.absorb_guidance = AsyncMock(return_value=True)

    await asyncio.sleep(0.3)

    try:
        yield {"daemon": daemon, "port": port}
    finally:
        await daemon.stop()


# ──────────────────────────────────────────────────────────
# job_create error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_empty_goal(ws_daemon) -> None:
    """job_create with empty goal string returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "goal": "",
                "request_id": "r1",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"
        assert resp["request_id"] == "r1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_missing_goal(ws_daemon) -> None:
    """job_create without goal field returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "request_id": "r2",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_submit_exception(ws_daemon) -> None:
    """job_create returns JOB_CREATE_FAILED when submit_task raises."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.submit_task = AsyncMock(side_effect=RuntimeError("backend down"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "goal": "Trigger failure",
                "request_id": "r3",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_CREATE_FAILED"
        assert "backend down" in resp["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_whitespace_only_goal(ws_daemon) -> None:
    """job_create with whitespace-only goal returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "goal": "   \t\n  ",
                "request_id": "r4",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


# ──────────────────────────────────────────────────────────
# job_status error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_status_missing_job_id(ws_daemon) -> None:
    """job_status without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_status",
                "request_id": "r5",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_status_not_found(ws_daemon) -> None:
    """job_status for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_status",
                "job_id": "nonexistent",
                "request_id": "r6",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_FOUND"


# ──────────────────────────────────────────────────────────
# job_pause error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_not_found(ws_daemon) -> None:
    """job_pause for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": "missing",
                "request_id": "r7",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_already_suspended(ws_daemon) -> None:
    """job_pause on already-suspended goal returns JOB_ALREADY_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(
        return_value=_FakeGoal(status="suspended")
    )

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": "abc12345",
                "request_id": "r8",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_ALREADY_PAUSED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_completed(ws_daemon) -> None:
    """job_pause on completed goal returns JOB_COMPLETED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(
        return_value=_FakeGoal(status="completed")
    )

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": "abc12345",
                "request_id": "r9",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_COMPLETED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_failed_goal(ws_daemon) -> None:
    """job_pause on failed goal returns JOB_COMPLETED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(
        return_value=_FakeGoal(status="failed")
    )

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": "abc12345",
                "request_id": "r10",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_COMPLETED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_suspend_exception(ws_daemon) -> None:
    """job_pause returns JOB_PAUSE_FAILED when suspend_goal raises."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._goal_engine
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="active"))
    ge.suspend_goal = AsyncMock(side_effect=RuntimeError("suspend error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": "abc12345",
                "request_id": "r11",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_PAUSE_FAILED"
        assert "suspend error" in resp["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_missing_job_id(ws_daemon) -> None:
    """job_pause without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "request_id": "r12",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


# ──────────────────────────────────────────────────────────
# job_resume error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_not_found(ws_daemon) -> None:
    """job_resume for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": "missing",
                "request_id": "r13",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_not_paused(ws_daemon) -> None:
    """job_resume on active (non-suspended) goal returns JOB_NOT_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(
        return_value=_FakeGoal(status="active")
    )

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": "abc12345",
                "request_id": "r14",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_PAUSED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_pending_not_paused(ws_daemon) -> None:
    """job_resume on pending goal returns JOB_NOT_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(
        return_value=_FakeGoal(status="pending")
    )

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": "abc12345",
                "request_id": "r15",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_PAUSED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_reactivate_exception(ws_daemon) -> None:
    """job_resume returns JOB_RESUME_FAILED when reactivate_goal raises."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._goal_engine
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="suspended"))
    ge.reactivate_goal = AsyncMock(side_effect=RuntimeError("reactivate error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": "abc12345",
                "request_id": "r16",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_RESUME_FAILED"
        assert "reactivate error" in resp["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_missing_job_id(ws_daemon) -> None:
    """job_resume without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "request_id": "r17",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_blocked_goal(ws_daemon) -> None:
    """job_resume on blocked goal succeeds (blocked is resumable)."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._goal_engine
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="blocked"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": "abc12345",
                "request_id": "r18",
            },
        )
        assert resp["type"] == "job_resume_response"
        assert resp["status"] == "pending"


# ──────────────────────────────────────────────────────────
# job_cancel error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_not_found(ws_daemon) -> None:
    """job_cancel for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.cancel_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_cancel",
                "job_id": "nonexistent",
                "request_id": "r19",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_exception(ws_daemon) -> None:
    """job_cancel returns JOB_CANCEL_FAILED when cancel_goal raises."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.cancel_goal = AsyncMock(side_effect=RuntimeError("cancel error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_cancel",
                "job_id": "abc12345",
                "request_id": "r20",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_CANCEL_FAILED"
        assert "cancel error" in resp["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_missing_job_id(ws_daemon) -> None:
    """job_cancel without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_cancel",
                "request_id": "r21",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


# ──────────────────────────────────────────────────────────
# job_dag error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_dag_not_found(ws_daemon) -> None:
    """job_dag for nonexistent root goal returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_dag",
                "job_id": "nonexistent",
                "request_id": "r22",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_dag_missing_job_id(ws_daemon) -> None:
    """job_dag without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_dag",
                "request_id": "r23",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


# ──────────────────────────────────────────────────────────
# job_guidance error paths and edge cases
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_missing_text(ws_daemon) -> None:
    """job_guidance without text returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "request_id": "r24",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"
        assert "text" in resp["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_empty_text(ws_daemon) -> None:
    """job_guidance with empty text returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "text": "   ",
                "request_id": "r25",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_missing_job_id(ws_daemon) -> None:
    """job_guidance without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "text": "Some guidance",
                "request_id": "r26",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_goal_not_found(ws_daemon) -> None:
    """job_guidance for nonexistent target goal returns GOAL_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "text": "Focus on tests",
                "request_id": "r27",
            },
        )
        assert resp["type"] == "error"
        assert resp["code"] == "GOAL_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_with_specific_goal_id(ws_daemon) -> None:
    """job_guidance with explicit goal_id targets that goal (scope=goal)."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._goal_engine
    child_goal = _FakeGoal(goal_id="child-1", status="active")
    ge.get_goal = AsyncMock(return_value=child_goal)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "goal_id": "child-1",
                "text": "Use pytest fixtures",
                "request_id": "r28",
            },
        )
        assert resp["type"] == "job_guidance_response"
        assert resp["goal_id"] == "child-1"
        assert resp["absorbed"] is True
        ge.absorb_guidance.assert_awaited_once_with("child-1", "Use pytest fixtures", scope="goal")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_rejected(ws_daemon) -> None:
    """job_guidance with absorbed=False when engine rejects guidance."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._goal_engine.absorb_guidance = AsyncMock(return_value=False)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "text": "Irrelevant guidance",
                "request_id": "r29",
            },
        )
        assert resp["type"] == "job_guidance_response"
        assert resp["absorbed"] is False


# ──────────────────────────────────────────────────────────
# AUTOPILOT_NOT_READY (service unavailable)
# ──────────────────────────────────────────────────────────


@pytest.fixture
async def ws_daemon_no_autopilot(tmp_path: Path):
    """Daemon with autopilot service set to None."""
    force_isolated_home(tmp_path / "soothe-home-noap")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
        http_port=port + 1,
    )
    config.agent.autonomous = config.agent.autonomous.model_copy(update={"poll_interval": 2})

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    # Null out autopilot service to simulate unavailable
    daemon._autopilot_service = None

    await asyncio.sleep(0.3)

    try:
        yield {"daemon": daemon, "port": port}
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_not_ready_all_handlers(ws_daemon_no_autopilot) -> None:
    """All autopilot WS handlers return AUTOPILOT_NOT_READY when service is None."""
    port = ws_daemon_no_autopilot["port"]

    messages = [
        {"type": "job_create", "goal": "test", "request_id": "nr-1"},
        {"type": "job_status", "job_id": "x", "request_id": "nr-2"},
        {"type": "job_pause", "job_id": "x", "request_id": "nr-3"},
        {"type": "job_resume", "job_id": "x", "request_id": "nr-4"},
        {"type": "job_cancel", "job_id": "x", "request_id": "nr-5"},
        {"type": "job_dag", "job_id": "x", "request_id": "nr-6"},
        {"type": "job_guidance", "job_id": "x", "text": "t", "request_id": "nr-7"},
    ]

    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await _drain_handshake(ws)
        for msg in messages:
            resp = await _send_recv(ws, msg)
            assert resp["type"] == "error", f"{msg['type']} should return error"
            assert resp["code"] == "AUTOPILOT_NOT_READY", (
                f"{msg['type']} should return AUTOPILOT_NOT_READY, got {resp['code']}"
            )
            assert resp["request_id"] == msg["request_id"]


# ──────────────────────────────────────────────────────────
# Concurrent clients
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_clients_independent(ws_daemon) -> None:
    """Two WebSocket clients operate independently on autopilot APIs."""
    port = ws_daemon["port"]
    uri = f"ws://127.0.0.1:{port}"

    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        await _drain_handshake(ws1)
        await _drain_handshake(ws2)

        # Client 1 creates a job
        resp1 = await _send_recv(
            ws1,
            {
                "type": "job_create",
                "goal": "Client 1 goal",
                "request_id": "c1-create",
            },
        )
        assert resp1["type"] == "job_create_response"
        assert resp1["request_id"] == "c1-create"

        # Client 2 queries status
        resp2 = await _send_recv(
            ws2,
            {
                "type": "job_status",
                "job_id": "abc12345",
                "request_id": "c2-status",
            },
        )
        assert resp2["type"] == "job_status_response"
        assert resp2["request_id"] == "c2-status"

        # Client 1 sends guidance
        resp3 = await _send_recv(
            ws1,
            {
                "type": "job_guidance",
                "job_id": "abc12345",
                "text": "From client 1",
                "request_id": "c1-guid",
            },
        )
        assert resp3["type"] == "job_guidance_response"
        assert resp3["request_id"] == "c1-guid"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_subscribe_isolation(ws_daemon) -> None:
    """Subscribe/unsubscribe on one client does not affect another."""
    port = ws_daemon["port"]
    uri = f"ws://127.0.0.1:{port}"

    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        await _drain_handshake(ws1)
        await _drain_handshake(ws2)

        # Client 1 subscribes
        resp1 = await _send_recv(
            ws1,
            {
                "type": "autopilot_subscribe",
                "request_id": "s1",
            },
        )
        assert resp1["type"] == "autopilot_subscribe_response"
        assert resp1["subscribed"] is True

        # Client 2 is not subscribed — unsubscribing should still work
        resp2 = await _send_recv(
            ws2,
            {
                "type": "autopilot_subscribe",
                "request_id": "s2",
            },
        )
        assert resp2["type"] == "autopilot_subscribe_response"
        assert resp2["subscribed"] is True

        # Client 1 unsubscribes
        resp3 = await _send_recv(
            ws1,
            {
                "type": "autopilot_unsubscribe",
                "request_id": "u1",
            },
        )
        assert resp3["type"] == "autopilot_unsubscribe_response"
        assert resp3["subscribed"] is False

        # Client 2 still subscribed — can still unsubscribe independently
        resp4 = await _send_recv(
            ws2,
            {
                "type": "autopilot_unsubscribe",
                "request_id": "u2",
            },
        )
        assert resp4["type"] == "autopilot_unsubscribe_response"
        assert resp4["subscribed"] is False


# ──────────────────────────────────────────────────────────
# Full error-path lifecycle
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_path_lifecycle(ws_daemon) -> None:
    """Exercise multiple error paths in a single connection."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._goal_engine

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _drain_handshake(ws)

        # 1. Create with empty goal → INVALID_REQUEST
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "goal": "",
                "request_id": "e1",
            },
        )
        assert resp["code"] == "INVALID_REQUEST"

        # 2. Successful create
        resp = await _send_recv(
            ws,
            {
                "type": "job_create",
                "goal": "Valid goal",
                "request_id": "e2",
            },
        )
        assert resp["type"] == "job_create_response"
        job_id = resp["job_id"]

        # 3. Pause on pending (not terminal, not suspended) → success
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="active"))
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": job_id,
                "request_id": "e3",
            },
        )
        assert resp["type"] == "job_pause_response"

        # 4. Pause again → JOB_ALREADY_PAUSED
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="suspended"))
        resp = await _send_recv(
            ws,
            {
                "type": "job_pause",
                "job_id": job_id,
                "request_id": "e4",
            },
        )
        assert resp["code"] == "JOB_ALREADY_PAUSED"

        # 5. Resume from suspended → success
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": job_id,
                "request_id": "e5",
            },
        )
        assert resp["type"] == "job_resume_response"

        # 6. Resume again (now pending) → JOB_NOT_PAUSED
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="pending"))
        resp = await _send_recv(
            ws,
            {
                "type": "job_resume",
                "job_id": job_id,
                "request_id": "e6",
            },
        )
        assert resp["code"] == "JOB_NOT_PAUSED"

        # 7. Guidance with empty text → INVALID_REQUEST
        resp = await _send_recv(
            ws,
            {
                "type": "job_guidance",
                "job_id": job_id,
                "text": "",
                "request_id": "e7",
            },
        )
        assert resp["code"] == "INVALID_REQUEST"

        # 8. Cancel → success
        resp = await _send_recv(
            ws,
            {
                "type": "job_cancel",
                "job_id": job_id,
                "request_id": "e8",
            },
        )
        assert resp["type"] == "job_cancel_response"
