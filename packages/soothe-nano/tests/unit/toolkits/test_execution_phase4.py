"""Phase 4 execution tools: retention cleanup, tail_background_log, capped stdout."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

from soothe_nano.toolkits.execution import (
    RunBackgroundTool,
    TailBackgroundLogTool,
    _cleanup_stale_background_logs,
)


class TestBackgroundLogRetention:
    def test_cleanup_removes_stale_logs(self, tmp_path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        stale = log_dir / "bg-stale.log"
        stale.write_text("old output", encoding="utf-8")
        old_time = time.time() - (10 * 86400)
        os.utime(stale, (old_time, old_time))
        fresh = log_dir / "bg-fresh.log"
        fresh.write_text("fresh output", encoding="utf-8")

        _cleanup_stale_background_logs(log_dir, retention_days=7)

        assert not stale.exists()
        assert fresh.exists()

    def test_cleanup_noop_when_retention_zero(self, tmp_path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        stale = log_dir / "bg-stale.log"
        stale.write_text("old", encoding="utf-8")
        old_time = time.time() - (30 * 86400)
        os.utime(stale, (old_time, old_time))

        _cleanup_stale_background_logs(log_dir, retention_days=0)

        assert stale.exists()

    def test_run_background_prunes_stale_logs_on_spawn(self, tmp_path) -> None:
        log_dir = tmp_path / ".soothe" / "background"
        log_dir.mkdir(parents=True)
        stale = log_dir / "bg-stale.log"
        stale.write_text("stale", encoding="utf-8")
        old_time = time.time() - (10 * 86400)
        os.utime(stale, (old_time, old_time))

        tool = RunBackgroundTool(
            workspace_root=str(tmp_path),
            background_log_retention_days=7,
        )

        class FakeProc:
            pid = 55555

        with patch("soothe_nano.toolkits.execution.subprocess.Popen", return_value=FakeProc()):
            result = tool._run("sleep 30")

        assert result["pid"] == 55555
        assert not stale.exists()


class TestTailBackgroundLog:
    def test_returns_last_n_lines(self, tmp_path) -> None:
        log_dir = tmp_path / "bg"
        log_dir.mkdir()
        log_path = log_dir / "bg-123.log"
        log_path.write_text("\n".join(f"line-{i}" for i in range(100)), encoding="utf-8")

        tool = TailBackgroundLogTool(background_log_dir=str(log_dir))
        result = tool._run(pid=123, lines=5)

        assert "line-99" in result
        assert "line-95" in result
        assert "line-0" not in result

    def test_missing_log_returns_error(self, tmp_path) -> None:
        tool = TailBackgroundLogTool(background_log_dir=str(tmp_path))
        result = tool._run(pid=99999, lines=10)
        assert "log file not found" in result

    def test_invalid_pid_rejected(self) -> None:
        tool = TailBackgroundLogTool()
        assert "invalid process ID" in tool._run(pid=0)
        assert "invalid process ID" in tool._run(pid=-1)
