"""Integration tests for RFC-228 Autopilot Job IPC WebSocket commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

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


class _FakeGoal:
    """Mock Goal object for testing."""

    def __init__(
        self,
        goal_id: str = "test1234",
        status: str = "pending",
        description: str = "Integration test goal",
        priority: int = 50,
    ) -> None:
        self.id = goal_id
        self.status = status
        self.description = description
        self.priority = priority
        self.error = None
        self.depends_on = []
        self.assigned_loop_id = None


@pytest.fixture
async def daemon_with_autopilot_ws(tmp_path: Path):
    """Daemon with WebSocket transport for RFC-228 integration tests."""
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

    # Mock AutopilotService methods
    test_goal = _FakeGoal(goal_id="abc12345", status="pending")
    daemon._autopilot_service.submit_task = AsyncMock(return_value=test_goal)
    daemon._autopilot_service.get_goal = AsyncMock(return_value=test_goal)
    daemon._autopilot_service.cancel_goal = AsyncMock(
        return_value=_FakeGoal(goal_id="abc12345", status="cancelled")
    )
    daemon._autopilot_service.list_goals = AsyncMock(return_value=[test_goal])
    daemon._autopilot_service.dag_snapshot = AsyncMock(
        return_value={
            "nodes": [
                {"id": "abc12345", "status": "pending", "description": "Root goal"},
                {"id": "child-1", "status": "active", "assigned_loop_id": "loop-w1"},
            ],
            "edges": [],
        }
    )

    # Mock GoalEngine methods
    daemon._autopilot_service._goal_engine.suspend_goal = AsyncMock(
        return_value=_FakeGoal(goal_id="abc12345", status="suspended")
    )
    daemon._autopilot_service._goal_engine.reactivate_goal = AsyncMock(
        return_value=_FakeGoal(goal_id="abc12345", status="pending")
    )
    daemon._autopilot_service._goal_engine.absorb_guidance = AsyncMock(return_value=True)
    daemon._autopilot_service._goal_engine.get_goal = AsyncMock(return_value=test_goal)

    await asyncio.sleep(0.5)

    try:
        yield {
            "daemon": daemon,
            "ws_port": port,
        }
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_create_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_create creates goal and returns job_id."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send job_create
        await ws.send(
            json.dumps(
                {
                    "type": "job_create",
                    "goal": "Build integration test feature",
                    "request_id": "req-create-1",
                }
            )
        )

        # Receive response
        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_create_response"
        assert msg["job_id"] == "abc12345"
        assert msg["status"] == "pending"
        assert msg["request_id"] == "req-create-1"

        # Verify AutopilotService.submit_task was called
        daemon._autopilot_service.submit_task.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_status_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_status returns goal counts and worker assignments."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send job_status
        await ws.send(
            json.dumps(
                {
                    "type": "job_status",
                    "job_id": "abc12345",
                    "request_id": "req-status-1",
                }
            )
        )

        # Receive response
        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_status_response"
        assert msg["job_id"] == "abc12345"
        assert msg["status"] == "pending"
        assert msg["active_goals"] == 1  # child-1 is active
        assert msg["completed_goals"] == 0
        assert msg["total_goals"] == 2
        assert len(msg["workers"]) == 1
        assert msg["workers"][0]["goal_id"] == "child-1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_resume_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_pause and job_resume control goal execution."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Update goal status to active for pause test (handler uses goal_engine.get_goal)
        active_goal = _FakeGoal(goal_id="abc12345", status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal
        daemon._autopilot_service._goal_engine.get_goal.return_value = active_goal

        # Send job_pause
        await ws.send(
            json.dumps(
                {
                    "type": "job_pause",
                    "job_id": "abc12345",
                    "request_id": "req-pause-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_pause_response"
        assert msg["job_id"] == "abc12345"
        assert msg["status"] == "suspended"

        # Update goal status to suspended for resume test (handler uses goal_engine.get_goal)
        suspended_goal = _FakeGoal(goal_id="abc12345", status="suspended")
        daemon._autopilot_service.get_goal.return_value = suspended_goal
        daemon._autopilot_service._goal_engine.get_goal.return_value = suspended_goal

        # Send job_resume
        await ws.send(
            json.dumps(
                {
                    "type": "job_resume",
                    "job_id": "abc12345",
                    "request_id": "req-resume-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_resume_response"
        assert msg["job_id"] == "abc12345"
        assert msg["status"] == "pending"

        # Verify GoalEngine methods called
        daemon._autopilot_service._goal_engine.suspend_goal.assert_awaited()
        daemon._autopilot_service._goal_engine.reactivate_goal.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_cancel cancels goal and descendants."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send job_cancel
        await ws.send(
            json.dumps(
                {
                    "type": "job_cancel",
                    "job_id": "abc12345",
                    "request_id": "req-cancel-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_cancel_response"
        assert msg["job_id"] == "abc12345"
        assert msg["status"] == "cancelled"

        # Verify AutopilotService.cancel_goal was called
        daemon._autopilot_service.cancel_goal.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_dag_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_dag returns DAG snapshot for visualization."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send job_dag
        await ws.send(
            json.dumps(
                {
                    "type": "job_dag",
                    "job_id": "abc12345",
                    "request_id": "req-dag-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_dag_response"
        assert msg["job_id"] == "abc12345"
        assert "dag" in msg
        assert "nodes" in msg["dag"]
        assert "edges" in msg["dag"]
        assert len(msg["dag"]["nodes"]) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_guidance absorbs user guidance."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send job_guidance
        await ws.send(
            json.dumps(
                {
                    "type": "job_guidance",
                    "job_id": "abc12345",
                    "text": "Focus on integration tests",
                    "request_id": "req-guid-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "job_guidance_response"
        assert msg["job_id"] == "abc12345"
        assert msg["goal_id"] == "abc12345"  # Defaults to job_id
        assert msg["absorbed"] is True

        # Verify GoalEngine.absorb_guidance was called
        daemon._autopilot_service._goal_engine.absorb_guidance.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_subscribe_unsubscribe_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket autopilot_subscribe enables worker event stream."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Send autopilot_subscribe
        await ws.send(
            json.dumps(
                {
                    "type": "autopilot_subscribe",
                    "request_id": "req-sub-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "autopilot_subscribe_response"
        assert "client_id" in msg
        assert msg["subscribed"] is True

        # Send autopilot_unsubscribe
        await ws.send(
            json.dumps(
                {
                    "type": "autopilot_unsubscribe",
                    "request_id": "req-unsub-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "autopilot_unsubscribe_response"
        assert msg["subscribed"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_handling_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket handlers return proper error responses."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Test INVALID_REQUEST (missing job_id)
        await ws.send(
            json.dumps(
                {
                    "type": "job_status",
                    "request_id": "req-err-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_REQUEST"
        assert msg["request_id"] == "req-err-1"

        # Test JOB_NOT_FOUND
        await ws.send(
            json.dumps(
                {
                    "type": "job_status",
                    "job_id": "nonexistent",
                    "request_id": "req-err-2",
                }
            )
        )

        # Mock returns None for nonexistent job
        daemon_with_autopilot_ws["daemon"]._autopilot_service.get_goal.return_value = None

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "error"
        assert msg["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_request_id_propagation_via_websocket(daemon_with_autopilot_ws) -> None:
    """All WebSocket responses preserve request_id."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # Test multiple handlers preserve request_id
        handlers_to_test = [
            ("job_create", {"goal": "test"}, "req-1"),
            ("job_status", {"job_id": "abc12345"}, "req-2"),
            ("job_dag", {"job_id": "abc12345"}, "req-3"),
        ]

        for handler_type, extra_fields, req_id in handlers_to_test:
            msg_dict = {"type": handler_type, **extra_fields, "request_id": req_id}
            await ws.send(json.dumps(msg_dict))

            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(response)

            assert msg.get("request_id") == req_id, f"{handler_type} response missing request_id"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_sequence_via_websocket(daemon_with_autopilot_ws) -> None:
    """Complete job lifecycle via WebSocket: create → pause → resume → cancel."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _drain_handshake(ws)
        # 1. Create job
        await ws.send(
            json.dumps(
                {
                    "type": "job_create",
                    "goal": "Lifecycle test",
                    "request_id": "seq-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "job_create_response"
        job_id = msg["job_id"]

        # 2. Check status
        await ws.send(
            json.dumps(
                {
                    "type": "job_status",
                    "job_id": job_id,
                    "request_id": "seq-2",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "job_status_response"

        # 3. Pause job (update status to active first)
        active_goal = _FakeGoal(goal_id=job_id, status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal
        daemon._autopilot_service._goal_engine.get_goal.return_value = active_goal

        await ws.send(
            json.dumps(
                {
                    "type": "job_pause",
                    "job_id": job_id,
                    "request_id": "seq-3",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "job_pause_response"

        # 4. Resume job (update status to suspended)
        suspended_goal = _FakeGoal(goal_id=job_id, status="suspended")
        daemon._autopilot_service.get_goal.return_value = suspended_goal
        daemon._autopilot_service._goal_engine.get_goal.return_value = suspended_goal

        await ws.send(
            json.dumps(
                {
                    "type": "job_resume",
                    "job_id": job_id,
                    "request_id": "seq-4",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "job_resume_response"

        # 5. Cancel job
        await ws.send(
            json.dumps(
                {
                    "type": "job_cancel",
                    "job_id": job_id,
                    "request_id": "seq-5",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "job_cancel_response"

        # Verify all operations completed
        daemon._autopilot_service.submit_task.assert_awaited()
        daemon._autopilot_service._goal_engine.suspend_goal.assert_awaited()
        daemon._autopilot_service._goal_engine.reactivate_goal.assert_awaited()
        daemon._autopilot_service.cancel_goal.assert_awaited()
