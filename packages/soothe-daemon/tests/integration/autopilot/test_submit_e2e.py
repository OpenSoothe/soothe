"""M9 integration test: HTTP autopilot submit → worker dispatch → goal completion."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon import SootheDaemon

from ..daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)


class _FakeAutopilotRunner:
    """Stub LoopRunner that emits a terminal GoalCompletionChunk."""

    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id

    async def run(self, request: Any):  # noqa: ANN401
        job = request.autopilot_job
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.goal_completion",
                "goal_id": job.goal_id,
                "outcome": "completed",
                "attempt": job.attempt,
                "context_contribution": {
                    "plan_steps_executed": [],
                    "files_touched": {},
                    "findings": [],
                    "tool_call_stats": {"counts_by_name": {}, "failures_by_name": {}},
                },
                "plan_result_status": "complete",
                "evidence_summary": (
                    "Integration test goal completed with substantive verified evidence."
                ),
            },
        )

    async def cancel(self) -> None:
        return None


@pytest.fixture
async def isolated_daemon_with_fake_runner(tmp_path: Path):
    """Daemon with autopilot dispatch patched to a fake worker."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
        http_port=port,
    )
    config.agent.autonomous = config.agent.autonomous.model_copy(update={"poll_interval": 1})
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)

    def _fake_create(loop_id: str) -> _FakeAutopilotRunner:
        return _FakeAutopilotRunner(loop_id)

    await daemon.start()
    assert daemon._autopilot_service is not None
    assert daemon._runner_factory is not None
    daemon._runner_factory.create_runner = _fake_create  # type: ignore[method-assign]
    consensus_mock = AsyncMock()
    consensus_mock.ainvoke.return_value.content = (
        "DECISION: accept\nREASONING: Integration test consensus."
    )
    daemon._autopilot_service._consensus_model = consensus_mock
    await asyncio.sleep(0.5)

    try:
        yield {
            "daemon": daemon,
            "http_port": port,
        }
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_http_submit_to_completion(isolated_daemon_with_fake_runner) -> None:
    """HTTP submit → AutopilotService → fake worker → goal completed."""
    port = isolated_daemon_with_fake_runner["http_port"]

    import aiohttp

    async with aiohttp.ClientSession() as session:
        submit_resp = await session.post(
            f"http://127.0.0.1:{port}/api/v1/autopilot/submit",
            json={"description": "integration test task", "priority": 50},
        )
        assert submit_resp.status == 200
        submit_data = await submit_resp.json()
        assert submit_data["transport"] == "live"
        goal_id = submit_data["goal_id"]

        # Nudge scheduling once (loop also ticks on poll_interval).
        svc = isolated_daemon_with_fake_runner["daemon"]._autopilot_service
        await svc._schedule_ready_goals()

        terminal_status = None
        for _ in range(120):
            await asyncio.sleep(0.1)
            goal_resp = await session.get(
                f"http://127.0.0.1:{port}/api/v1/autopilot/goals/{goal_id}",
            )
            assert goal_resp.status == 200
            goal = (await goal_resp.json())["goal"]
            terminal_status = goal["status"]
            if terminal_status in ("completed", "failed", "suspended"):
                break

        assert terminal_status == "completed"
