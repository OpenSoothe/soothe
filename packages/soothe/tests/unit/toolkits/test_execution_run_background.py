"""Unit tests for run_background spawn and workspace behavior."""

from __future__ import annotations

import os
import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from soothe.toolkits.execution import RunBackgroundTool, _kill_process_tree


class TestRunBackgroundSpawn:
    """Background process lifecycle (real subprocess, short-lived)."""

    def test_run_background_starts_process_and_returns_pid(self) -> None:
        tool = RunBackgroundTool()
        result = tool._run(command="sleep 30")
        assert result["status"] == "running"
        assert isinstance(result["pid"], int)
        assert result["pid"] > 0
        try:
            os.kill(result["pid"], 0)
        finally:
            _kill_process_tree(result["pid"], sig=signal.SIGKILL)

    def test_run_background_uses_workspace_cwd(self, tmp_path) -> None:
        tool = RunBackgroundTool(workspace_root=str(tmp_path))
        marker = tmp_path / "bg-marker.txt"
        # Background shell writes marker then sleeps so we can verify cwd.
        cmd = f"echo started > {marker.name} && sleep 30"
        result = tool._run(command=cmd)
        assert result["status"] == "running"
        pid = result["pid"]
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not marker.exists():
                time.sleep(0.05)
            assert marker.exists()
            assert marker.read_text(encoding="utf-8").strip() == "started"
        finally:
            _kill_process_tree(pid, sig=signal.SIGKILL)


class TestRunBackgroundMocked:
    """Fast unit tests with mocked subprocess."""

    def test_run_background_security_denied(self) -> None:
        tool = RunBackgroundTool()
        result = tool._run("sudo rm -rf /")
        assert result["status"] == "error"
        assert result["pid"] is None
        assert "Command blocked by security rule" in result["message"]

    def test_run_background_popen_failure(self) -> None:
        tool = RunBackgroundTool()
        with patch(
            "soothe.toolkits.execution.subprocess.Popen",
            side_effect=OSError("spawn failed"),
        ):
            result = tool._run("sleep 1")
        assert result["status"] == "error"
        assert "spawn failed" in result["message"]

    def test_run_background_passes_cwd_to_popen(self, tmp_path) -> None:
        tool = RunBackgroundTool(workspace_root=str(tmp_path))
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 12345

        def fake_popen(*_args, **kwargs):
            captured.update(kwargs)
            return FakeProc()

        with patch("soothe.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
            result = tool._run("sleep 1")

        assert result["pid"] == 12345
        assert captured.get("cwd") == str(tmp_path.resolve())

    def test_run_background_translates_virtual_paths(self, tmp_path) -> None:
        security = MagicMock()
        security.allow_paths_outside_workspace = False
        tool = RunBackgroundTool(workspace_root=str(tmp_path), security_config=security)
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 99

        def fake_popen(cmd, **_kwargs):
            captured["cmd"] = cmd
            return FakeProc()

        with patch("soothe.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
            tool._run("cat /README.md")

        ws = str(tmp_path.resolve())
        assert captured["cmd"] == f"cat {ws}/README.md"

    def test_run_background_runtime_workspace_overrides_root(self, tmp_path) -> None:
        client_ws = tmp_path / "client"
        client_ws.mkdir()
        tool = RunBackgroundTool(workspace_root="/daemon/default")
        runtime = MagicMock()
        runtime.config = {"configurable": {"workspace": str(client_ws)}}
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 77

        def fake_popen(_cmd, **kwargs):
            captured.update(kwargs)
            return FakeProc()

        with patch("soothe.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
            tool._run("sleep 1", runtime=runtime)

        assert captured.get("cwd") == str(client_ws.resolve())
