"""Tests for Autopilot dreaming mode (soothe.cognition.dreaming)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.cognition.dreaming import DreamingMode


class TestDreamingModeInit:
    """Tests for DreamingMode initialization."""

    def test_default_intervals(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        assert mode._consolidation_interval == 300
        assert mode._health_check_interval == 60

    def test_custom_intervals(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path, consolidation_interval=60, health_check_interval=10)
        assert mode._consolidation_interval == 60
        assert mode._health_check_interval == 10

    def test_initial_state(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        assert mode.state == "idle"
        assert mode._running is False


@pytest.mark.asyncio
class TestDreamingMode:
    """Tests for DreamingMode behavior."""

    async def test_stop_sets_running_false(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        mode._running = True
        mode.stop()
        assert mode._running is False

    async def test_write_status_creates_file(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        mode._state = "dreaming"
        mode._write_status()

        status_file = tmp_path / "autopilot" / "status.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["state"] == "dreaming"
        assert "timestamp" in data

    async def test_write_outbox_creates_message(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        mode._write_outbox("dreaming_entered", {})

        outbox_dir = tmp_path / "autopilot" / "outbox"
        assert outbox_dir.exists()
        files = list(outbox_dir.glob("*.json"))
        assert len(files) == 1

    async def test_poll_inbox_empty(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        result = mode._poll_inbox()
        assert result is None

    async def test_poll_inbox_with_task(self, tmp_path: Path) -> None:
        inbox_dir = tmp_path / "autopilot" / "inbox"
        inbox_dir.mkdir(parents=True)
        inbox_dir.joinpath("task.md").write_text("---\ntype: task_submit\npriority: 80\n---\n\nDo something.\n")

        mode = DreamingMode(soothe_home=tmp_path)
        result = mode._poll_inbox()
        assert result is not None
        assert result["type"] == "task_submit"

    async def test_poll_inbox_signal_resume(self, tmp_path: Path) -> None:
        inbox_dir = tmp_path / "autopilot" / "inbox"
        inbox_dir.mkdir(parents=True)
        inbox_dir.joinpath("wake.md").write_text("---\ntype: signal_resume\n---\n\nWake up.\n")

        mode = DreamingMode(soothe_home=tmp_path)
        result = mode._poll_inbox()
        assert result is not None
        assert result["type"] == "signal_resume"

    async def test_run_consolidation_no_protocols(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        await mode._run_consolidation()
        # Should not raise even without protocols

    async def test_run_consolidation_calls_memory_consolidate(self, tmp_path: Path) -> None:
        mock_memory = AsyncMock()
        mock_memory.consolidate = AsyncMock()
        mode = DreamingMode(soothe_home=tmp_path, memory_protocol=mock_memory)
        await mode._run_consolidation()
        mock_memory.consolidate.assert_called_once()

    async def test_run_consolidation_calls_memory_compact(self, tmp_path: Path) -> None:
        # Use spec so mock only has 'compact', not 'consolidate'
        mock_memory = MagicMock(spec=["compact"])
        mock_memory.compact = AsyncMock()
        mode = DreamingMode(soothe_home=tmp_path, memory_protocol=mock_memory)
        await mode._run_consolidation()
        mock_memory.compact.assert_called_once()

    async def test_run_consolidation_calls_context_compact(self, tmp_path: Path) -> None:
        mock_memory = AsyncMock()
        mock_context = AsyncMock()
        mock_context.compact = AsyncMock()
        mode = DreamingMode(soothe_home=tmp_path, memory_protocol=mock_memory, context_protocol=mock_context)
        await mode._run_consolidation()
        mock_context.compact.assert_called_once()

    async def test_run_health_check(self, tmp_path: Path) -> None:
        mode = DreamingMode(soothe_home=tmp_path)
        await mode._run_health_check()
        # Should not raise

    async def test_health_check_warns_low_space(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        mode = DreamingMode(soothe_home=tmp_path)
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = (0, 0, 10 * 1024 * 1024)  # 10MB free
            with caplog.at_level(logging.WARNING):
                await mode._run_health_check()
        assert "Low disk space" in caplog.text
