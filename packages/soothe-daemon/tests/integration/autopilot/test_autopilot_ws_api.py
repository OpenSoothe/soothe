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


async def _handshake(ws) -> None:
    """Complete the protocol-1 handshake (RFC-450).

    The daemon sends one unsolicited ``status`` preamble on connect, then waits
    for ``connection_init`` and replies with a single ``connection_ack``.
    """
    # Drain the initial status preamble.
    preamble = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
    assert preamble.get("type") == "status", f"expected status preamble, got {preamble}"
    # Initiate the protocol-1 handshake.
    await ws.send(
        json.dumps(
            {
                "proto": "1",
                "type": "connection_init",
                "params": {
                    "client_version": "test",
                    "accept_proto": ["1"],
                    "capabilities": ["streaming", "batch", "heartbeat", "receipts"],
                },
            }
        )
    )
    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
    assert ack.get("type") == "connection_ack", f"expected connection_ack, got {ack}"


def _request(method: str, params: dict, rid: str) -> dict:
    """Build a protocol-1 RPC request envelope."""
    return {"proto": "1", "type": "request", "method": method, "params": params, "id": rid}


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
    )
    config.agent.autopilot = config.agent.autopilot.model_copy(update={"poll_interval": 2})

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

    ge = svc._ce
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
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_create", {"goal": ""}, "r1"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS
        assert resp["id"] == "r1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_missing_goal(ws_daemon) -> None:
    """job_create without goal field returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_create", {}, "r2"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_submit_exception(ws_daemon) -> None:
    """job_create returns JOB_CREATE_FAILED when submit_task raises."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.submit_task = AsyncMock(side_effect=RuntimeError("backend down"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_create", {"goal": "Trigger failure"}, "r3"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32500  # JOB_CREATE_FAILED
        assert "backend down" in resp["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_whitespace_only_goal(ws_daemon) -> None:
    """job_create with whitespace-only goal returns INVALID_REQUEST (handler-level)."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_create", {"goal": "   \t\n  "}, "r4"))
        assert resp["type"] == "error"
        # Schema accepts a whitespace goal (length >= 1); the handler strips it
        # and rejects with INVALID_REQUEST (-32600) per RFC-450 §7.3.
        assert resp["error"]["code"] == -32600  # INVALID_REQUEST


# ──────────────────────────────────────────────────────────
# job_status error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_status_missing_job_id(ws_daemon) -> None:
    """job_status without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_status", {}, "r5"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_status_not_found(ws_daemon) -> None:
    """job_status for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_status", {"job_id": "nonexistent"}, "r6"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32201  # JOB_NOT_FOUND


# ──────────────────────────────────────────────────────────
# job_pause error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_not_found(ws_daemon) -> None:
    """job_pause for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {"job_id": "missing"}, "r7"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32201  # JOB_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_already_suspended(ws_daemon) -> None:
    """job_pause on already-suspended goal returns JOB_ALREADY_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=_FakeGoal(status="suspended"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {"job_id": "abc12345"}, "r8"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32300  # JOB_ALREADY_PAUSED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_completed(ws_daemon) -> None:
    """job_pause on completed goal returns JOB_COMPLETED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=_FakeGoal(status="completed"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {"job_id": "abc12345"}, "r9"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32302  # JOB_COMPLETED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_failed_goal(ws_daemon) -> None:
    """job_pause on failed goal returns JOB_COMPLETED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=_FakeGoal(status="failed"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {"job_id": "abc12345"}, "r10"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32302  # JOB_COMPLETED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_suspend_exception(ws_daemon) -> None:
    """job_pause returns JOB_PAUSE_FAILED when suspend_goal raises."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._ce
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="active"))
    ge.suspend_goal = AsyncMock(side_effect=RuntimeError("suspend error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {"job_id": "abc12345"}, "r11"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32501  # JOB_PAUSE_FAILED
        assert "suspend error" in resp["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_missing_job_id(ws_daemon) -> None:
    """job_pause without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_pause", {}, "r12"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


# ──────────────────────────────────────────────────────────
# job_resume error paths
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_not_found(ws_daemon) -> None:
    """job_resume for nonexistent job returns JOB_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {"job_id": "missing"}, "r13"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32201  # JOB_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_not_paused(ws_daemon) -> None:
    """job_resume on active (non-suspended) goal returns JOB_NOT_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=_FakeGoal(status="active"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {"job_id": "abc12345"}, "r14"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32301  # JOB_NOT_PAUSED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_pending_not_paused(ws_daemon) -> None:
    """job_resume on pending goal returns JOB_NOT_PAUSED."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=_FakeGoal(status="pending"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {"job_id": "abc12345"}, "r15"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32301  # JOB_NOT_PAUSED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_reactivate_exception(ws_daemon) -> None:
    """job_resume returns JOB_RESUME_FAILED when reactivate_goal raises."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._ce
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="suspended"))
    ge.reactivate_goal = AsyncMock(side_effect=RuntimeError("reactivate error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {"job_id": "abc12345"}, "r16"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32502  # JOB_RESUME_FAILED
        assert "reactivate error" in resp["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_missing_job_id(ws_daemon) -> None:
    """job_resume without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {}, "r17"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_resume_blocked_goal(ws_daemon) -> None:
    """job_resume on blocked goal succeeds (blocked is resumable)."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._ce
    ge.get_goal = AsyncMock(return_value=_FakeGoal(status="blocked"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_resume", {"job_id": "abc12345"}, "r18"))
        assert resp["type"] == "response"
        assert resp["result"]["status"] == "pending"


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
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_cancel", {"job_id": "nonexistent"}, "r19"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32201  # JOB_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_exception(ws_daemon) -> None:
    """job_cancel returns JOB_CANCEL_FAILED when cancel_goal raises."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service.cancel_goal = AsyncMock(side_effect=RuntimeError("cancel error"))

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_cancel", {"job_id": "abc12345"}, "r20"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32503  # JOB_CANCEL_FAILED
        assert "cancel error" in resp["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_missing_job_id(ws_daemon) -> None:
    """job_cancel without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_cancel", {}, "r21"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


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
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_dag", {"job_id": "nonexistent"}, "r22"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32201  # JOB_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_dag_missing_job_id(ws_daemon) -> None:
    """job_dag without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_dag", {}, "r23"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


# ──────────────────────────────────────────────────────────
# job_guidance error paths and edge cases
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_missing_content(ws_daemon) -> None:
    """job_guidance without content returns INVALID_PARAMS (schema validator)."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_guidance", {"job_id": "abc12345"}, "r24"))
        assert resp["type"] == "error"
        # The JobGuidanceParams model requires content; missing it fails schema validation (-32602) with
        # the reason in data.errors.
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS
        errors = resp["error"].get("data", {}).get("errors", [])
        assert any("content" in e for e in errors), errors


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_empty_content(ws_daemon) -> None:
    """job_guidance with whitespace-only content returns INVALID_REQUEST (handler)."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(
            ws, _request("job_guidance", {"job_id": "abc12345", "content": "   "}, "r25")
        )
        assert resp["type"] == "error"
        # Schema accepts whitespace content (truthy); the handler strips it and
        # rejects with INVALID_REQUEST (-32600) per RFC-450 §7.3.
        assert resp["error"]["code"] == -32600  # INVALID_REQUEST


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_missing_job_id(ws_daemon) -> None:
    """job_guidance without job_id returns INVALID_REQUEST."""
    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(ws, _request("job_guidance", {"content": "Some guidance"}, "r26"))
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_goal_not_found(ws_daemon) -> None:
    """job_guidance for nonexistent target goal returns GOAL_NOT_FOUND."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=None)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(
            ws,
            _request(
                "job_guidance",
                {"job_id": "abc12345", "content": "Focus on tests"},
                "r27",
            ),
        )
        assert resp["type"] == "error"
        assert resp["error"]["code"] == -32202  # GOAL_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_with_specific_goal_id(ws_daemon) -> None:
    """job_guidance with explicit goal_id targets that goal (scope=goal)."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._ce
    child_goal = _FakeGoal(goal_id="child-1", status="active")
    ge.get_goal = AsyncMock(return_value=child_goal)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(
            ws,
            _request(
                "job_guidance",
                {"job_id": "abc12345", "goal_id": "child-1", "content": "Use pytest fixtures"},
                "r28",
            ),
        )
        assert resp["type"] == "response"
        assert resp["result"]["goal_id"] == "child-1"
        assert resp["result"]["absorbed"] is True
        ge.absorb_guidance.assert_awaited_once_with("child-1", "Use pytest fixtures", scope="goal")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_rejected(ws_daemon) -> None:
    """job_guidance with absorbed=False when engine rejects guidance."""
    daemon = ws_daemon["daemon"]
    daemon._autopilot_service._ce.absorb_guidance = AsyncMock(return_value=False)

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)
        resp = await _send_recv(
            ws,
            _request(
                "job_guidance",
                {"job_id": "abc12345", "content": "Irrelevant guidance"},
                "r29",
            ),
        )
        assert resp["type"] == "response"
        assert resp["result"]["absorbed"] is False


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
    )
    config.agent.autopilot = config.agent.autopilot.model_copy(update={"poll_interval": 2})

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
        _request("job_create", {"goal": "test"}, "nr-1"),
        _request("job_status", {"job_id": "x"}, "nr-2"),
        _request("job_pause", {"job_id": "x"}, "nr-3"),
        _request("job_resume", {"job_id": "x"}, "nr-4"),
        _request("job_cancel", {"job_id": "x"}, "nr-5"),
        _request("job_dag", {"job_id": "x"}, "nr-6"),
        _request("job_guidance", {"job_id": "x", "content": "t"}, "nr-7"),
    ]

    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await _handshake(ws)
        for msg in messages:
            resp = await _send_recv(ws, msg)
            assert resp["type"] == "error", f"{msg['method']} should return error"
            assert resp["error"]["code"] == -32402, (  # AUTOPILOT_NOT_READY
                f"{msg['method']} should return AUTOPILOT_NOT_READY, got {resp['error']['code']}"
            )
            assert resp["id"] == msg["id"]


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
        await _handshake(ws1)
        await _handshake(ws2)

        # Client 1 creates a job
        resp1 = await _send_recv(
            ws1, _request("job_create", {"goal": "Client 1 goal"}, "c1-create")
        )
        assert resp1["type"] == "response"
        assert resp1["id"] == "c1-create"

        # Client 2 queries status
        resp2 = await _send_recv(ws2, _request("job_status", {"job_id": "abc12345"}, "c2-status"))
        assert resp2["type"] == "response"
        assert resp2["id"] == "c2-status"

        # Client 1 sends guidance
        resp3 = await _send_recv(
            ws1,
            _request(
                "job_guidance",
                {"job_id": "abc12345", "content": "From client 1"},
                "c1-guid",
            ),
        )
        assert resp3["type"] == "response"
        assert resp3["id"] == "c1-guid"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_subscribe_isolation(ws_daemon) -> None:
    """Subscribe/unsubscribe on one client does not affect another."""
    port = ws_daemon["port"]
    uri = f"ws://127.0.0.1:{port}"

    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        await _handshake(ws1)
        await _handshake(ws2)

        # Client 1 subscribes (subscribe method on autopilot_events → next event)
        resp1 = await _send_recv(
            ws1,
            {
                "proto": "1",
                "type": "subscribe",
                "method": "autopilot_events",
                "params": {},
                "id": "s1",
            },
        )
        assert resp1["type"] == "next"
        assert resp1["payload"]["subscribed"] is True

        # Client 2 is not subscribed — subscribing should still work
        resp2 = await _send_recv(
            ws2,
            {
                "proto": "1",
                "type": "subscribe",
                "method": "autopilot_events",
                "params": {},
                "id": "s2",
            },
        )
        assert resp2["type"] == "next"
        assert resp2["payload"]["subscribed"] is True

        # Client 1 unsubscribes (→ response with subscribed: false)
        resp3 = await _send_recv(
            ws1,
            {
                "proto": "1",
                "type": "unsubscribe",
                "id": "u1",
            },
        )
        assert resp3["type"] == "response"
        assert resp3["result"]["subscribed"] is False

        # Client 2 still subscribed — can still unsubscribe independently
        resp4 = await _send_recv(
            ws2,
            {
                "proto": "1",
                "type": "unsubscribe",
                "id": "u2",
            },
        )
        assert resp4["type"] == "response"
        assert resp4["result"]["subscribed"] is False


# ──────────────────────────────────────────────────────────
# Full error-path lifecycle
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_path_lifecycle(ws_daemon) -> None:
    """Exercise multiple error paths in a single connection."""
    daemon = ws_daemon["daemon"]
    ge = daemon._autopilot_service._ce

    async with websockets.connect(f"ws://127.0.0.1:{ws_daemon['port']}") as ws:
        await _handshake(ws)

        # 1. Create with empty goal → INVALID_REQUEST
        resp = await _send_recv(ws, _request("job_create", {"goal": ""}, "e1"))
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS

        # 2. Successful create
        resp = await _send_recv(ws, _request("job_create", {"goal": "Valid goal"}, "e2"))
        assert resp["type"] == "response"
        job_id = resp["result"]["job_id"]

        # 3. Pause on pending (not terminal, not suspended) → success
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="active"))
        resp = await _send_recv(ws, _request("job_pause", {"job_id": job_id}, "e3"))
        assert resp["type"] == "response"

        # 4. Pause again → JOB_ALREADY_PAUSED
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="suspended"))
        resp = await _send_recv(ws, _request("job_pause", {"job_id": job_id}, "e4"))
        assert resp["error"]["code"] == -32300  # JOB_ALREADY_PAUSED

        # 5. Resume from suspended → success
        resp = await _send_recv(ws, _request("job_resume", {"job_id": job_id}, "e5"))
        assert resp["type"] == "response"

        # 6. Resume again (now pending) → JOB_NOT_PAUSED
        ge.get_goal = AsyncMock(return_value=_FakeGoal(goal_id=job_id, status="pending"))
        resp = await _send_recv(ws, _request("job_resume", {"job_id": job_id}, "e6"))
        assert resp["error"]["code"] == -32301  # JOB_NOT_PAUSED

        # 7. Guidance with empty content → INVALID_REQUEST
        resp = await _send_recv(
            ws, _request("job_guidance", {"job_id": job_id, "content": ""}, "e7")
        )
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS

        # 8. Cancel → success
        resp = await _send_recv(ws, _request("job_cancel", {"job_id": job_id}, "e8"))
        assert resp["type"] == "response"
