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
    daemon._autopilot_service._ce.suspend_goal = AsyncMock(
        return_value=_FakeGoal(goal_id="abc12345", status="suspended")
    )
    daemon._autopilot_service._ce.reactivate_goal = AsyncMock(
        return_value=_FakeGoal(goal_id="abc12345", status="pending")
    )
    daemon._autopilot_service._ce.absorb_guidance = AsyncMock(return_value=True)
    daemon._autopilot_service._ce.get_goal = AsyncMock(return_value=test_goal)

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
        await _handshake(ws)
        # Send job_create
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_create",
                    "params": {"goal": "Build integration test feature"},
                    "id": "req-create-1",
                }
            )
        )

        # Receive response
        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        assert msg["id"] == "req-create-1"
        assert msg["result"]["job_id"] == "abc12345"
        assert msg["result"]["status"] == "pending"

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
        await _handshake(ws)
        # Send job_status
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_status",
                    "params": {"job_id": "abc12345"},
                    "id": "req-status-1",
                }
            )
        )

        # Receive response
        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        result = msg["result"]
        assert result["job_id"] == "abc12345"
        assert result["status"] == "pending"
        assert result["active_goals"] == 1  # child-1 is active
        assert result["completed_goals"] == 0
        assert result["total_goals"] == 2
        assert len(result["workers"]) == 1
        assert result["workers"][0]["goal_id"] == "child-1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_pause_resume_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_pause and job_resume control goal execution."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Update goal status to active for pause test (handler uses goal_engine.get_goal)
        active_goal = _FakeGoal(goal_id="abc12345", status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal
        daemon._autopilot_service._ce.get_goal.return_value = active_goal

        # Send job_pause
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_pause",
                    "params": {"job_id": "abc12345"},
                    "id": "req-pause-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "abc12345"
        assert msg["result"]["status"] == "suspended"

        # Update goal status to suspended for resume test (handler uses goal_engine.get_goal)
        suspended_goal = _FakeGoal(goal_id="abc12345", status="suspended")
        daemon._autopilot_service.get_goal.return_value = suspended_goal
        daemon._autopilot_service._ce.get_goal.return_value = suspended_goal

        # Send job_resume
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_resume",
                    "params": {"job_id": "abc12345"},
                    "id": "req-resume-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "abc12345"
        assert msg["result"]["status"] == "pending"

        # Verify GoalEngine methods called
        daemon._autopilot_service._ce.suspend_goal.assert_awaited()
        daemon._autopilot_service._ce.reactivate_goal.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_cancel_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_cancel cancels goal and descendants."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Send job_cancel
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_cancel",
                    "params": {"job_id": "abc12345"},
                    "id": "req-cancel-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "abc12345"
        assert msg["result"]["status"] == "cancelled"

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
        await _handshake(ws)
        # Send job_dag
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_dag",
                    "params": {"job_id": "abc12345"},
                    "id": "req-dag-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        result = msg["result"]
        assert result["job_id"] == "abc12345"
        assert "dag" in result
        assert "nodes" in result["dag"]
        assert "edges" in result["dag"]
        assert len(result["dag"]["nodes"]) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_guidance_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket job_guidance absorbs user guidance."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Send job_guidance
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_guidance",
                    "params": {
                        "job_id": "abc12345",
                        "content": "Focus on integration tests",
                    },
                    "id": "req-guid-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        result = msg["result"]
        assert result["job_id"] == "abc12345"
        assert result["goal_id"] == "abc12345"  # Defaults to job_id
        assert result["absorbed"] is True

        # Verify GoalEngine.absorb_guidance was called
        daemon._autopilot_service._ce.absorb_guidance.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_subscribe_unsubscribe_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket autopilot_subscribe enables worker event stream."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Send autopilot_subscribe (subscribe method on autopilot_events)
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "subscribe",
                    "method": "autopilot_events",
                    "params": {},
                    "id": "req-sub-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "next"
        assert msg["id"] == "req-sub-1"
        assert "client_id" in msg["payload"]
        assert msg["payload"]["subscribed"] is True

        # Send autopilot_unsubscribe
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "unsubscribe",
                    "id": "req-unsub-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "response"
        assert msg["id"] == "req-unsub-1"
        assert msg["result"]["subscribed"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_handling_via_websocket(daemon_with_autopilot_ws) -> None:
    """WebSocket handlers return proper error responses."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Test INVALID_PARAMS (missing job_id — schema enforces)
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_status",
                    "params": {},
                    "id": "req-err-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "error"
        assert msg["error"]["code"] == -32602  # INVALID_PARAMS (schema requires job_id)
        assert msg["id"] == "req-err-1"

        # Test JOB_NOT_FOUND
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_status",
                    "params": {"job_id": "nonexistent"},
                    "id": "req-err-2",
                }
            )
        )

        # Mock returns None for nonexistent job
        daemon_with_autopilot_ws["daemon"]._autopilot_service.get_goal.return_value = None

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)

        assert msg["type"] == "error"
        assert msg["error"]["code"] == -32201  # JOB_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.integration
async def test_request_id_propagation_via_websocket(daemon_with_autopilot_ws) -> None:
    """All WebSocket responses preserve request id."""
    ws_port = daemon_with_autopilot_ws["ws_port"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # Test multiple handlers preserve request id
        handlers_to_test = [
            ("job_create", {"goal": "test"}, "req-1"),
            ("job_status", {"job_id": "abc12345"}, "req-2"),
            ("job_dag", {"job_id": "abc12345"}, "req-3"),
        ]

        for method, params, req_id in handlers_to_test:
            await ws.send(
                json.dumps(
                    {
                        "proto": "1",
                        "type": "request",
                        "method": method,
                        "params": params,
                        "id": req_id,
                    }
                )
            )

            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(response)

            assert msg.get("id") == req_id, f"{method} response missing id"
            assert msg["type"] == "response", f"{method} did not return response"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_job_sequence_via_websocket(daemon_with_autopilot_ws) -> None:
    """Complete job lifecycle via WebSocket: create → pause → resume → cancel."""
    ws_port = daemon_with_autopilot_ws["ws_port"]
    daemon = daemon_with_autopilot_ws["daemon"]

    import websockets

    uri = f"ws://127.0.0.1:{ws_port}"

    async with websockets.connect(uri) as ws:
        await _handshake(ws)
        # 1. Create job
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_create",
                    "params": {"goal": "Lifecycle test"},
                    "id": "seq-1",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "response"
        job_id = msg["result"]["job_id"]

        # 2. Check status
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_status",
                    "params": {"job_id": job_id},
                    "id": "seq-2",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "response"

        # 3. Pause job (update status to active first)
        active_goal = _FakeGoal(goal_id=job_id, status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal
        daemon._autopilot_service._ce.get_goal.return_value = active_goal

        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_pause",
                    "params": {"job_id": job_id},
                    "id": "seq-3",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "response"

        # 4. Resume job (update status to suspended)
        suspended_goal = _FakeGoal(goal_id=job_id, status="suspended")
        daemon._autopilot_service.get_goal.return_value = suspended_goal
        daemon._autopilot_service._ce.get_goal.return_value = suspended_goal

        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_resume",
                    "params": {"job_id": job_id},
                    "id": "seq-4",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "response"

        # 5. Cancel job
        await ws.send(
            json.dumps(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_cancel",
                    "params": {"job_id": job_id},
                    "id": "seq-5",
                }
            )
        )

        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(response)
        assert msg["type"] == "response"

        # Verify all operations completed
        daemon._autopilot_service.submit_task.assert_awaited()
        daemon._autopilot_service._ce.suspend_goal.assert_awaited()
        daemon._autopilot_service._ce.reactivate_goal.assert_awaited()
        daemon._autopilot_service.cancel_goal.assert_awaited()
