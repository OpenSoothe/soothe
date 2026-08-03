"""Unmocked Autopilot CE paths (IG-678 P1-6): guidance + pause on real CE."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
    stop_daemon_safely,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_ce_submit_guidance_and_pause(tmp_path: Path) -> None:
    """Daemon AutopilotService uses a real ContextEngine for guidance/pause."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path=tmp_path, websocket_port=port)
    config.agent.autopilot = config.agent.autopilot.model_copy(
        update={"enabled": True, "poll_interval": 2}
    )

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    try:
        svc = daemon._autopilot_service
        assert svc is not None
        ce = svc._ce

        # Real submit — no AsyncMock
        goal = await svc.submit_task("Real CE job", workspace=str(tmp_path / "ws"))
        assert goal.id
        fetched = await ce.get_goal(goal.id)
        assert fetched is not None
        assert fetched.description == "Real CE job"

        # Real absorb_guidance (async)
        ok = await ce.absorb_guidance(goal.id, "Prefer integration tests", scope="goal")
        assert ok is True
        again = await ce.get_goal(goal.id)
        assert again is not None
        assert again.guidance_accumulated[-1]["text"] == "Prefer integration tests"

        child = await ce.create_goal("child step", parent_id=goal.id)
        paused = await svc.pause_job(goal.id, reason="user_pause")
        assert paused is not None
        assert paused.status == "suspended"
        child_after = await ce.get_goal(child.id)
        assert child_after is not None
        assert child_after.status == "suspended"
    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submit_with_rail_binds_interpreter(tmp_path: Path) -> None:
    """``--rail spike`` path binds interpreter and fires job_start builtins."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path=tmp_path, websocket_port=port)
    config.agent.autopilot = config.agent.autopilot.model_copy(
        update={"enabled": False, "poll_interval": 2}
    )

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    try:
        svc = daemon._autopilot_service
        assert svc is not None
        assert svc._rail_interpreter is not None

        goal = await svc.submit_task("Spike auth options", rail_id="spike")
        assert goal.rail_id == "spike"
        # job_start → decompose_parallel should have spawned scout children
        goals = await svc.list_goals()
        children = [g for g in goals if g.parent_id == goal.id]
        assert len(children) >= 1
        assert all(g.rail_id == "spike" or g.role == "scout" for g in children)
    finally:
        await stop_daemon_safely(daemon)
