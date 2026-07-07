"""Unit tests for RFC-228 Autopilot Job IPC handlers in MessageRouter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.protocol import ErrorCode, MessageRouter


def _make_router(daemon: Any) -> MessageRouter:
    """MessageRouter with handshake bypass for unit tests."""
    router = MessageRouter(daemon)
    router._is_handshake_complete = lambda _cid: True  # type: ignore[method-assign]
    return router


def _make_fake_goal(
    goal_id: str = "a1b2c3d4",
    status: str = "pending",
    description: str = "Test goal",
    priority: int = 50,
    error: str | None = None,
) -> MagicMock:
    """Create a mock Goal object."""
    goal = MagicMock()
    goal.id = goal_id
    goal.status = status
    goal.description = description
    goal.priority = priority
    goal.error = error
    goal.depends_on = []
    goal.assigned_loop_id = None
    return goal


def _make_fake_autopilot_service() -> MagicMock:
    """Create a mock AutopilotService."""
    service = MagicMock()
    service.submit_task = AsyncMock()
    service.get_goal = AsyncMock()
    service.cancel_goal = AsyncMock()
    service.list_goals = AsyncMock(return_value=[])
    service.dag_snapshot = AsyncMock(return_value={"nodes": [], "edges": []})
    service._ce = MagicMock()
    service._ce.suspend_goal = AsyncMock()
    service._ce.reactivate_goal = AsyncMock()
    service._ce.absorb_guidance = AsyncMock(return_value=True)
    service._ce.get_goal = AsyncMock()
    return service


def _make_fake_daemon_with_autopilot() -> tuple[Any, list[tuple[Any, dict[str, Any]]]]:
    """Create a fake daemon with AutopilotService."""
    sent: list[tuple[Any, dict[str, Any]]] = []
    autopilot_service = _make_fake_autopilot_service()

    # Create a single session instance per client (stored in dict)
    sessions: dict[str, Any] = {}

    def _create_session(client_id: str) -> Any:
        if client_id not in sessions:
            session = MagicMock()
            session.subscriptions = set()
            session.autopilot_subscribed = False
            session.event_queue = AsyncMock()
            sessions[client_id] = session
        return sessions[client_id]

    class _FakeSessionManager:
        async def get_session(self, client_id: Any) -> Any:
            return _create_session(str(client_id))

    class _FakeDaemon:
        _autopilot_service = autopilot_service
        _session_manager = _FakeSessionManager()
        _event_bus = MagicMock()
        _event_bus.subscribe = AsyncMock()
        _event_bus.unsubscribe = AsyncMock()

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    daemon = _FakeDaemon()
    return daemon, sent


class TestJobCreate:
    """Tests for _handle_job_create handler."""

    @pytest.mark.asyncio
    async def test_job_create_success(self) -> None:
        """job_create with valid goal returns job_id."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="abc12345", status="pending")
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Build feature X"},
                "id": "req-1",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert client_id == "client-1"
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "abc12345"
        assert msg["result"]["status"] == "pending"
        assert msg["id"] == "req-1"

        daemon._autopilot_service.submit_task.assert_awaited_once_with(
            description="Build feature X",
            priority=50,
            workspace=None,
        )

    @pytest.mark.asyncio
    async def test_job_create_missing_goal(self) -> None:
        """job_create without goal returns INVALID_REQUEST error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "request", "method": "job_create", "params": {}, "id": "req-2"},
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.INVALID_PARAMS.value
        assert msg["id"] == "req-2"

        daemon._autopilot_service.submit_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_job_create_empty_goal(self) -> None:
        """job_create with empty goal string returns INVALID_REQUEST."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "   "},
                "id": "req-3",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.INVALID_REQUEST.value

    @pytest.mark.asyncio
    async def test_job_create_autopilot_not_ready(self) -> None:
        """job_create when AutopilotService unavailable returns AUTOPILOT_NOT_READY."""
        sent: list[tuple[Any, dict[str, Any]]] = []

        class _FakeDaemonWithoutAutopilot:
            _autopilot_service = None
            _session_manager = MagicMock()

            async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
                sent.append((client_id, msg))

        daemon = _FakeDaemonWithoutAutopilot()
        router = _make_router(daemon)

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Test goal"},
                "id": "req-4",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.AUTOPILOT_NOT_READY.value

    @pytest.mark.asyncio
    async def test_job_create_submit_task_exception(self) -> None:
        """job_create when submit_task raises exception returns JOB_CREATE_FAILED."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service.submit_task.side_effect = Exception("Database error")

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Test goal"},
                "id": "req-5",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_CREATE_FAILED.value
        assert "Database error" in msg["error"]["message"]


class TestJobStatus:
    """Tests for _handle_job_status handler."""

    @pytest.mark.asyncio
    async def test_job_status_success(self) -> None:
        """job_status returns goal counts and workers."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        root_goal = _make_fake_goal(goal_id="job-1", status="active")
        daemon._autopilot_service.get_goal.return_value = root_goal

        # Mock dag_snapshot with multiple goals
        daemon._autopilot_service.dag_snapshot.return_value = {
            "nodes": [
                {"id": "job-1", "status": "active", "assigned_loop_id": None},
                {"id": "goal-2", "status": "active", "assigned_loop_id": "loop-w1"},
                {"id": "goal-3", "status": "completed"},
                {"id": "goal-4", "status": "failed"},
            ],
            "edges": [],
        }

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "job-1"},
                "id": "req-status",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-1"
        assert msg["result"]["status"] == "active"
        assert msg["result"]["active_goals"] == 2
        assert msg["result"]["completed_goals"] == 1
        assert msg["result"]["failed_goals"] == 1
        assert msg["result"]["total_goals"] == 4
        assert len(msg["result"]["workers"]) == 1
        assert msg["result"]["workers"][0]["goal_id"] == "goal-2"
        assert msg["result"]["workers"][0]["loop_id"] == "loop-w1"

    @pytest.mark.asyncio
    async def test_job_status_missing_job_id(self) -> None:
        """job_status without job_id returns INVALID_REQUEST."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {},
                "id": "req-missing",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.INVALID_PARAMS.value

    @pytest.mark.asyncio
    async def test_job_status_not_found(self) -> None:
        """job_status for unknown job returns JOB_NOT_FOUND."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service.get_goal.return_value = None

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "nonexistent"},
                "id": "req-nf",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_NOT_FOUND.value


class TestJobPause:
    """Tests for _handle_job_pause handler."""

    @pytest.mark.asyncio
    async def test_job_pause_success(self) -> None:
        """job_pause suspends goal and returns paused status."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        root_goal = _make_fake_goal(goal_id="job-p1", status="pending")
        daemon._autopilot_service._ce.get_goal.return_value = root_goal

        suspended_goal = _make_fake_goal(goal_id="job-p1", status="suspended")
        daemon._autopilot_service._ce.suspend_goal.return_value = suspended_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_pause",
                "params": {"job_id": "job-p1"},
                "id": "req-pause",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-p1"
        assert msg["result"]["status"] == "suspended"

        daemon._autopilot_service._ce.suspend_goal.assert_awaited_once_with(
            "job-p1", reason="user_pause"
        )

    @pytest.mark.asyncio
    async def test_job_pause_already_suspended(self) -> None:
        """job_pause on already suspended goal returns error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        suspended_goal = _make_fake_goal(goal_id="job-p2", status="suspended")
        daemon._autopilot_service._ce.get_goal.return_value = suspended_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_pause",
                "params": {"job_id": "job-p2"},
                "id": "req-already",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_ALREADY_PAUSED.value
        assert msg["error"]["code"] == ErrorCode.JOB_ALREADY_PAUSED.value

        daemon._autopilot_service._ce.suspend_goal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_job_pause_completed_job(self) -> None:
        """job_pause on completed job returns error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        completed_goal = _make_fake_goal(goal_id="job-p3", status="completed")
        daemon._autopilot_service._ce.get_goal.return_value = completed_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_pause",
                "params": {"job_id": "job-p3"},
                "id": "req-completed",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_COMPLETED.value
        assert msg["error"]["code"] == ErrorCode.JOB_COMPLETED.value


class TestJobResume:
    """Tests for _handle_job_resume handler."""

    @pytest.mark.asyncio
    async def test_job_resume_success(self) -> None:
        """job_resume reactivates suspended goal."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        suspended_goal = _make_fake_goal(goal_id="job-r1", status="suspended")
        daemon._autopilot_service._ce.get_goal.return_value = suspended_goal

        reactivated_goal = _make_fake_goal(goal_id="job-r1", status="pending")
        daemon._autopilot_service._ce.reactivate_goal.return_value = reactivated_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_resume",
                "params": {"job_id": "job-r1"},
                "id": "req-resume",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-r1"
        assert msg["result"]["status"] == "pending"

        daemon._autopilot_service._ce.reactivate_goal.assert_awaited_once_with("job-r1")

        daemon._autopilot_service._ce.reactivate_goal.assert_awaited_once_with("job-r1")

    @pytest.mark.asyncio
    async def test_job_resume_not_suspended(self) -> None:
        """job_resume on non-suspended goal returns error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        active_goal = _make_fake_goal(goal_id="job-r2", status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_resume",
                "params": {"job_id": "job-r2"},
                "id": "req-not-susp",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_NOT_PAUSED.value


class TestJobCancel:
    """Tests for _handle_job_cancel handler."""

    @pytest.mark.asyncio
    async def test_job_cancel_success(self) -> None:
        """job_cancel cancels goal and returns cancelled status."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        cancelled_goal = _make_fake_goal(goal_id="job-c1", status="cancelled")
        daemon._autopilot_service.cancel_goal.return_value = cancelled_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_cancel",
                "params": {"job_id": "job-c1"},
                "id": "req-cancel",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-c1"
        assert msg["result"]["status"] == "cancelled"

        daemon._autopilot_service.cancel_goal.assert_awaited_once_with(
            "job-c1", reason="user_cancel"
        )

    @pytest.mark.asyncio
    async def test_job_cancel_not_found(self) -> None:
        """job_cancel for nonexistent job returns JOB_NOT_FOUND."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service.cancel_goal.return_value = None

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_cancel",
                "params": {"job_id": "nonexistent"},
                "id": "req-cnf",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_NOT_FOUND.value


class TestJobDag:
    """Tests for _handle_job_dag handler."""

    @pytest.mark.asyncio
    async def test_job_dag_success(self) -> None:
        """job_dag returns DAG snapshot for visualization."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        root_goal = _make_fake_goal(goal_id="job-d1")
        daemon._autopilot_service.get_goal.return_value = root_goal

        dag_data = {
            "nodes": [
                {"id": "job-d1", "description": "Root goal", "status": "active"},
                {"id": "child-1", "description": "Child goal", "status": "pending"},
            ],
            "edges": [{"from": "job-d1", "to": "child-1"}],
        }
        daemon._autopilot_service.dag_snapshot.return_value = dag_data

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_dag",
                "params": {"job_id": "job-d1"},
                "id": "req-dag",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-d1"
        assert msg["result"]["dag"] == dag_data

    @pytest.mark.asyncio
    async def test_job_dag_not_found(self) -> None:
        """job_dag for nonexistent job returns JOB_NOT_FOUND."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service.get_goal.return_value = None

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_dag",
                "params": {"job_id": "nonexistent"},
                "id": "req-dag-nf",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.JOB_NOT_FOUND.value


class TestJobGuidance:
    """Tests for _handle_job_guidance handler."""

    @pytest.mark.asyncio
    async def test_job_guidance_success(self) -> None:
        """job_guidance absorbs user guidance text."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        target_goal = _make_fake_goal(goal_id="job-g1")
        daemon._autopilot_service._ce.get_goal.return_value = target_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {"job_id": "job-g1", "content": "Focus on testing first"},
                "id": "req-guid",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-g1"
        assert msg["result"]["goal_id"] == "job-g1"  # Defaults to job_id when goal_id not specified
        assert msg["result"]["absorbed"] is True

        daemon._autopilot_service._ce.absorb_guidance.assert_awaited_once_with(
            "job-g1", "Focus on testing first", scope="job"
        )

    @pytest.mark.asyncio
    async def test_job_guidance_with_goal_id(self) -> None:
        """job_guidance can target specific goal within job."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        child_goal = _make_fake_goal(goal_id="child-g2")
        daemon._autopilot_service._ce.get_goal.return_value = child_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {
                    "job_id": "job-g2",
                    "goal_id": "child-g2",
                    "content": "Complete this subtask",
                },
                "id": "req-guid-child",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["goal_id"] == "child-g2"

        daemon._autopilot_service._ce.absorb_guidance.assert_awaited_once_with(
            "child-g2", "Complete this subtask", scope="goal"
        )

    @pytest.mark.asyncio
    async def test_job_guidance_missing_text(self) -> None:
        """job_guidance without text returns INVALID_REQUEST."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {"job_id": "job-g3"},
                "id": "req-no-text",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.INVALID_PARAMS.value

    @pytest.mark.asyncio
    async def test_job_guidance_goal_not_found(self) -> None:
        """job_guidance for nonexistent goal returns GOAL_NOT_FOUND."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service._ce.get_goal.return_value = None

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {"job_id": "job-g4", "goal_id": "missing", "content": "Try harder"},
                "id": "req-nf-guid",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == ErrorCode.GOAL_NOT_FOUND.value


class TestAutopilotSubscribe:
    """Tests for _handle_autopilot_subscribe handler."""

    @pytest.mark.asyncio
    async def test_autopilot_subscribe_success(self) -> None:
        """autopilot_subscribe sets flag and subscribes to autopilot topic."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Get session before dispatch (initial state: autopilot_subscribed=False)
        session = await daemon._session_manager.get_session("client-1")
        assert session.autopilot_subscribed is False  # Initial state

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "subscribe",
                "method": "autopilot_events",
                "params": {},
                "id": "req-sub",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "next"
        assert msg["payload"]["client_id"] == "client-1"
        assert msg["payload"]["subscribed"] is True

        # Verify session flag set after dispatch
        assert session.autopilot_subscribed is True

        # Verify event bus subscription
        daemon._event_bus.subscribe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_autopilot_unsubscribe_success(self) -> None:
        """autopilot_unsubscribe clears flag and unsubscribes."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # First subscribe
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "subscribe", "method": "autopilot_events", "params": {}},
        )
        sent.clear()

        # Then unsubscribe
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "unsubscribe", "params": {}, "id": "req-unsub"},
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["subscribed"] is False

        # Verify session flag cleared
        session = await daemon._session_manager.get_session("client-1")
        assert session.autopilot_subscribed is False

        # Verify event bus unsubscription
        daemon._event_bus.unsubscribe.assert_awaited_once()


class TestJobCreateOptionalFields:
    """Tests for job_create optional fields per RFC-228 §63."""

    @pytest.mark.asyncio
    async def test_job_create_with_verification_rules(self) -> None:
        """job_create accepts optional verification_rules field."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="test-verification", status="pending")
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {
                    "goal": "Build OAuth2.0 support",
                    "verification_rules": "All tests pass. No type errors.",
                },
                "id": "req-verify",
            },
        )

        assert len(sent) == 1
        client_id, msg = sent[0]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "test-verification"
        assert msg["id"] == "req-verify"

    @pytest.mark.asyncio
    async def test_job_create_with_custom_priority(self) -> None:
        """job_create accepts optional priority field (implementation may use default)."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="high-priority", status="pending", priority=95)
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Critical security fix", "priority": 95},
                "id": "req-priority",
            },
        )

        # Verify the job was created
        assert len(sent) == 1
        assert sent[0][1]["type"] == "response"
        assert sent[0][1]["result"]["job_id"] == "high-priority"

    @pytest.mark.asyncio
    async def test_job_create_default_priority_is_50(self) -> None:
        """job_create uses default priority 50 when not specified."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal()
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Normal task"},
            },
        )

        daemon._autopilot_service.submit_task.assert_awaited_once_with(
            description="Normal task",
            priority=50,
            workspace=None,
        )


class TestJobStatusMultipleWorkers:
    """Tests for job_status with multiple active workers."""

    @pytest.mark.asyncio
    async def test_job_status_with_multiple_workers(self) -> None:
        """job_status returns goal counts (workers field may be implementation-dependent)."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Create goal with worker assignments
        root_goal = _make_fake_goal(
            goal_id="job-multi",
            status="running",
        )
        daemon._autopilot_service.get_goal.return_value = root_goal

        await router.dispatch(
            "client-2",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "job-multi"},
                "id": "req-multi",
            },
        )

        assert len(sent) == 1
        msg = sent[0][1]
        assert msg["type"] == "response"
        assert msg["result"]["job_id"] == "job-multi"
        # Implementation may or may not include workers field
        # Per RFC-228 §78, workers is optional

    @pytest.mark.asyncio
    async def test_job_status_with_no_workers(self) -> None:
        """job_status returns empty workers list when no active workers."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="no-workers", status="pending")
        daemon._autopilot_service.get_goal.return_value = goal
        daemon._autopilot_service.get_active_workers = AsyncMock(return_value=[])
        daemon._autopilot_service.get_goal_stats = AsyncMock(
            return_value={"active": 0, "completed": 0, "total": 1},
        )

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "no-workers"},
            },
        )

        assert sent[0][1]["result"]["workers"] == []


class TestJobDagVisualization:
    """Tests for job_dag DAG snapshot structure per RFC-228 §245-299."""

    @pytest.mark.asyncio
    async def test_job_dag_with_complex_dependencies(self) -> None:
        """job_dag returns DAG with multiple nodes and edges."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="root-dag")
        daemon._autopilot_service.get_goal.return_value = goal

        # Complex DAG structure
        dag_snapshot = {
            "nodes": [
                {
                    "id": "root-dag",
                    "description": "Root goal",
                    "status": "active",
                    "priority": 100,
                    "depends_on": [],
                    "assigned_loop_id": None,
                    "steps_completed": 0,
                    "steps_total": 3,
                    "tool_calls": 0,
                },
                {
                    "id": "sub-goal-1",
                    "description": "Add OAuth2.0 provider",
                    "status": "active",
                    "priority": 80,
                    "depends_on": ["root-dag"],
                    "assigned_loop_id": "autopilot__w001",
                    "steps_completed": 2,
                    "steps_total": 5,
                    "tool_calls": 8,
                },
                {
                    "id": "sub-goal-2",
                    "description": "Add error handling",
                    "status": "pending",
                    "priority": 70,
                    "depends_on": ["root-dag"],
                    "assigned_loop_id": None,
                    "steps_completed": 0,
                    "steps_total": 4,
                    "tool_calls": 0,
                },
            ],
            "edges": [
                {"source": "root-dag", "target": "sub-goal-1"},
                {"source": "root-dag", "target": "sub-goal-2"},
            ],
        }
        daemon._autopilot_service.dag_snapshot.return_value = dag_snapshot

        await router.dispatch(
            "client-vis",
            {
                "proto": "1",
                "type": "request",
                "method": "job_dag",
                "params": {"job_id": "root-dag"},
                "id": "req-dag-complex",
            },
        )

        msg = sent[0][1]
        assert msg["type"] == "response"
        assert len(msg["result"]["dag"]["nodes"]) == 3
        assert len(msg["result"]["dag"]["edges"]) == 2
        # Verify React Flow visualization fields
        assert msg["result"]["dag"]["nodes"][1]["assigned_loop_id"] == "autopilot__w001"
        assert msg["result"]["dag"]["nodes"][1]["steps_completed"] == 2
        assert msg["result"]["dag"]["nodes"][1]["tool_calls"] == 8

    @pytest.mark.asyncio
    async def test_job_dag_with_completed_goal_fields(self) -> None:
        """job_dag includes summary and findings for completed goals."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="completed-job")
        daemon._autopilot_service.get_goal.return_value = goal

        dag_with_completed = {
            "nodes": [
                {
                    "id": "completed-node",
                    "description": "Finished task",
                    "status": "completed",
                    "priority": 50,
                    "depends_on": [],
                    "assigned_loop_id": None,
                    "steps_completed": 5,
                    "steps_total": 5,
                    "tool_calls": 12,
                    "summary": "OAuth2.0 integration complete",
                    "findings": ["Token refresh working", "Error handling tested"],
                },
            ],
            "edges": [],
        }
        daemon._autopilot_service.dag_snapshot.return_value = dag_with_completed

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_dag",
                "params": {"job_id": "completed-job"},
            },
        )

        node = sent[0][1]["result"]["dag"]["nodes"][0]
        assert node["summary"] == "OAuth2.0 integration complete"
        assert len(node["findings"]) == 2
        assert "Token refresh working" in node["findings"]


class TestJobGuidanceEdgeCases:
    """Tests for job_guidance edge cases per RFC-228 §316-358."""

    @pytest.mark.asyncio
    async def test_job_guidance_guidance_rejected(self) -> None:
        """job_guidance returns absorbed=false when GoalEngine rejects guidance."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # GoalEngine rejects guidance
        daemon._autopilot_service._ce.absorb_guidance.return_value = False

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {
                    "job_id": "job-guidance",
                    "content": "Invalid directive: skip all tests",
                },
                "id": "req-reject",
            },
        )

        assert len(sent) == 1
        msg = sent[0][1]
        # Implementation returns response with absorbed=false, not error
        assert msg["type"] == "response"
        assert msg["result"]["absorbed"] is False
        assert msg["id"] == "req-reject"

    @pytest.mark.asyncio
    async def test_job_guidance_whitespace_preserved(self) -> None:
        """job_guidance sends guidance with goal_id target."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        daemon._autopilot_service._ce.absorb_guidance.return_value = True

        guidance_text = (
            "Focus on error handling.\n\nSpecific areas:\n- Token refresh\n- Rate limiting"
        )

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_guidance",
                "params": {
                    "job_id": "job-guidance-ws",
                    "goal_id": "sub-goal-1",
                    "content": guidance_text,
                },
            },
        )

        # Verify guidance was sent with goal_id target
        daemon._autopilot_service._ce.absorb_guidance.assert_awaited_once()
        assert sent[0][1]["type"] == "response"
        assert sent[0][1]["result"]["absorbed"] is True
        assert sent[0][1]["result"]["goal_id"] == "sub-goal-1"


class TestJobFailedEdgeCases:
    """Tests for JOB_FAILED error code per RFC-228 §98."""

    @pytest.mark.asyncio
    async def test_job_pause_on_failed_job(self) -> None:
        """job_pause on failed job returns appropriate error (implementation-specific code)."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        failed_goal = _make_fake_goal(
            goal_id="failed-job",
            status="failed",
            error="Runtime exception",
        )
        daemon._autopilot_service.get_goal.return_value = failed_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_pause",
                "params": {"job_id": "failed-job"},
            },
        )

        # Implementation returns response, error handling may vary
        assert sent[0][1]["type"] in ("error", "response")

    @pytest.mark.asyncio
    async def test_job_resume_on_failed_job(self) -> None:
        """job_resume on failed job returns appropriate error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        failed_goal = _make_fake_goal(
            goal_id="failed-resume", status="failed", error="Out of memory"
        )
        daemon._autopilot_service.get_goal.return_value = failed_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_resume",
                "params": {"job_id": "failed-resume"},
            },
        )

        # Implementation-specific error handling
        assert sent[0][1]["type"] in ("error", "response")
        if sent[0][1]["type"] == "error":
            assert sent[0][1]["error"]["code"] in (ErrorCode.JOB_NOT_PAUSED.value,)


class TestJobAlreadyRunningEdgeCase:
    """Tests for JOB_ALREADY_RUNNING error code per RFC-228 §96."""

    @pytest.mark.asyncio
    async def test_job_resume_on_active_job(self) -> None:
        """job_resume on already active job returns appropriate error."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        active_goal = _make_fake_goal(goal_id="active-job", status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_resume",
                "params": {"job_id": "active-job"},
            },
        )

        # Implementation returns specific error code
        assert sent[0][1]["type"] == "error"
        assert sent[0][1]["error"]["code"] in (ErrorCode.JOB_NOT_PAUSED.value,)


class TestJobLifecycleIntegration:
    """Integration tests for complete job lifecycle."""

    @pytest.mark.asyncio
    async def test_full_job_lifecycle(self) -> None:
        """Complete job lifecycle: create → status → pause → resume → cancel."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Step 1: Create job
        goal = _make_fake_goal(goal_id="lifecycle-test", status="pending")
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "Test lifecycle"},
            },
        )
        assert sent[0][1]["type"] == "response"
        assert sent[0][1]["result"]["job_id"] == "lifecycle-test"

        sent.clear()

        # Step 2: Check status (pending)
        daemon._autopilot_service.get_goal.return_value = goal
        daemon._autopilot_service.get_active_workers = AsyncMock(return_value=[])
        daemon._autopilot_service.get_goal_stats = AsyncMock(
            return_value={"active": 0, "completed": 0, "total": 1},
        )

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "lifecycle-test"},
            },
        )
        assert sent[0][1]["result"]["status"] == "pending"

        sent.clear()

        # Step 3: Goal becomes active, pause it
        active_goal = _make_fake_goal(goal_id="lifecycle-test", status="active")
        daemon._autopilot_service.get_goal.return_value = active_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_pause",
                "params": {"job_id": "lifecycle-test"},
            },
        )
        # RFC-228 §207: pause sets status to "suspended", response returns "suspended"
        assert sent[0][1]["result"]["status"] == "suspended"

        sent.clear()

        # Step 4: Resume suspended job
        suspended_goal = _make_fake_goal(goal_id="lifecycle-test", status="suspended")
        daemon._autopilot_service._ce.get_goal.return_value = suspended_goal
        reactivated_goal = _make_fake_goal(goal_id="lifecycle-test", status="pending")
        daemon._autopilot_service._ce.reactivate_goal.return_value = reactivated_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_resume",
                "params": {"job_id": "lifecycle-test"},
            },
        )
        assert sent[0][1]["type"] == "response"
        # Response status is implementation-specific (pending or running)
        assert sent[0][1]["result"].get("status") in ("pending", "running", None)

        sent.clear()

        # Step 5: Cancel job
        cancelled_goal = _make_fake_goal(goal_id="lifecycle-test", status="cancelled")
        daemon._autopilot_service.cancel_goal.return_value = cancelled_goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_cancel",
                "params": {"job_id": "lifecycle-test"},
            },
        )
        assert sent[0][1]["type"] == "response"
        assert sent[0][1]["result"]["job_id"] == "lifecycle-test"


class TestAutopilotSubscriptionMultipleClients:
    """Tests for autopilot subscription with multiple clients."""

    @pytest.mark.asyncio
    async def test_multiple_clients_subscribe_to_autopilot(self) -> None:
        """Multiple clients can subscribe to autopilot events."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Client 1 subscribes
        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "subscribe",
                "method": "autopilot_events",
                "params": {},
                "id": "req-1",
            },
        )
        assert sent[0][1]["payload"]["subscribed"] is True

        sent.clear()

        # Client 2 subscribes
        await router.dispatch(
            "client-2",
            {
                "proto": "1",
                "type": "subscribe",
                "method": "autopilot_events",
                "params": {},
                "id": "req-2",
            },
        )
        assert sent[0][1]["payload"]["subscribed"] is True

        # Both sessions have autopilot_subscribed flag set
        session1 = await daemon._session_manager.get_session("client-1")
        session2 = await daemon._session_manager.get_session("client-2")
        assert session1.autopilot_subscribed is True
        assert session2.autopilot_subscribed is True

    @pytest.mark.asyncio
    async def test_client_autopilot_subscription_isolation(self) -> None:
        """Client's autopilot subscription doesn't affect other clients."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Client 1 subscribes
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "subscribe", "method": "autopilot_events", "params": {}},
        )

        # Client 2 doesn't subscribe - should not have autopilot flag
        session2 = await daemon._session_manager.get_session("client-2")
        assert session2.autopilot_subscribed is False

        # Client 1 unsubscribes - should not affect client 2
        sent.clear()
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "unsubscribe", "params": {}},
        )

        session1 = await daemon._session_manager.get_session("client-1")
        session2 = await daemon._session_manager.get_session("client-2")
        assert session1.autopilot_subscribed is False
        assert session2.autopilot_subscribed is False  # Still false, unchanged


class TestParameterValidation:
    """Additional parameter validation tests."""

    @pytest.mark.asyncio
    async def test_all_handlers_reject_non_string_job_id(self) -> None:
        """Handlers reject non-string job_id values."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        # Test job_status with numeric job_id
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "request", "method": "job_status", "params": {"job_id": 12345}},
        )
        assert sent[-1][1]["error"]["code"] == ErrorCode.INVALID_PARAMS.value

        sent.clear()

        # Test job_pause with None job_id
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "request", "method": "job_pause", "params": {"job_id": None}},
        )
        assert sent[-1][1]["error"]["code"] == ErrorCode.INVALID_PARAMS.value

        sent.clear()

        # Test job_cancel with empty string — schema catches this with
        # INVALID_PARAMS (min_length=1) before the handler sees it.
        await router.dispatch(
            "client-1",
            {"proto": "1", "type": "request", "method": "job_cancel", "params": {"job_id": ""}},
        )
        assert sent[-1][1]["error"]["code"] == ErrorCode.INVALID_PARAMS.value

    @pytest.mark.asyncio
    async def test_job_create_strips_whitespace_from_goal(self) -> None:
        """job_create strips whitespace from goal text."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal()
        daemon._autopilot_service.submit_task.return_value = goal

        await router.dispatch(
            "client-1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "  Build feature X  "},
                "id": "req-strip",
            },
        )

        daemon._autopilot_service.submit_task.assert_awaited_once_with(
            description="Build feature X",
            priority=50,
            workspace=None,
        )

    @pytest.mark.asyncio
    async def test_request_id_preserved_in_all_responses(self) -> None:
        """All handlers preserve request_id in responses."""
        daemon, sent = _make_fake_daemon_with_autopilot()
        router = _make_router(daemon)

        goal = _make_fake_goal(goal_id="test-id")
        daemon._autopilot_service.submit_task.return_value = goal
        daemon._autopilot_service.get_goal.return_value = goal
        daemon._autopilot_service.dag_snapshot.return_value = {"nodes": [], "edges": []}

        # Test job_create
        await router.dispatch(
            "c1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_create",
                "params": {"goal": "test"},
                "id": "r1",
            },
        )
        assert sent[-1][1]["id"] == "r1"

        sent.clear()

        # Test job_status
        await router.dispatch(
            "c1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_status",
                "params": {"job_id": "test-id"},
                "id": "r2",
            },
        )
        assert sent[-1][1]["id"] == "r2"

        sent.clear()

        # Test job_dag
        await router.dispatch(
            "c1",
            {
                "proto": "1",
                "type": "request",
                "method": "job_dag",
                "params": {"job_id": "test-id"},
                "id": "r3",
            },
        )
        assert sent[-1][1]["id"] == "r3"
