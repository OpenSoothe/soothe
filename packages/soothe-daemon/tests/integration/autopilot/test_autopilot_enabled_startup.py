"""Integration tests: agent.autopilot.enabled starts the scheduling loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enabled_config_starts_scheduling_and_monitor(tmp_path: Path) -> None:
    """Guarded pilot: enabled config starts AutopilotService + AutopilotMonitor loops."""
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
        assert svc._running is True
        assert svc._scheduling_task is not None
        assert not svc._scheduling_task.done()

        monitor = svc._monitor
        assert monitor is not None
        assert hasattr(monitor, "_verify_task")
        assert monitor._verify_task is not None
        assert not monitor._verify_task.done()
    finally:
        await daemon.stop()
