"""Unit tests for run_background spawn and workspace behavior."""

from __future__ import annotations

import os
import signal
import time
from unittest.mock import MagicMock, patch

from soothe_nano.toolkits.execution import (
    RunBackgroundTool,
    _kill_process_tree,
    _resolve_background_log_dir,
)


class TestRunBackgroundSpawn:
    """Background process lifecycle (real subprocess, short-lived)."""

    def test_run_background_starts_process_and_returns_pid(self) -> None:
        tool = RunBackgroundTool()
        result = tool._run(command="sleep 30")
        assert result["status"] == "running"
        assert isinstance(result["pid"], int)
        assert result["pid"] > 0
        assert result["log_path"]
        assert f"bg-{result['pid']}.log" in result["log_path"]
        try:
            os.kill(result["pid"], 0)
        finally:
            _kill_process_tree(result["pid"], sig=signal.SIGKILL)

    def test_run_background_writes_header_before_spawn(self, tmp_path) -> None:
        tool = RunBackgroundTool(workspace_root=str(tmp_path))
        result = tool._run(command='echo "header-test" && sleep 30')
        assert result["log_path"]
        content = open(result["log_path"], encoding="utf-8").read()
        assert "[soothe] background started" in content
        assert 'echo "header-test" && sleep 30' in content
        _kill_process_tree(result["pid"], sig=signal.SIGKILL)

    def test_run_background_captures_stdout_to_log(self, tmp_path) -> None:
        tool = RunBackgroundTool(workspace_root=str(tmp_path))
        result = tool._run(command='echo "bg-log-test" && sleep 30')
        assert result["status"] == "running"
        log_path = result["log_path"]
        assert log_path
        pid = result["pid"]
        try:
            deadline = time.time() + 5
            content = ""
            while time.time() < deadline:
                if os.path.exists(log_path):
                    content = open(log_path, encoding="utf-8").read()
                    if "bg-log-test" in content:
                        break
                time.sleep(0.05)
            assert "bg-log-test" in content
        finally:
            _kill_process_tree(pid, sig=signal.SIGKILL)

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
        assert result["log_path"] is None
        assert "Command blocked by security rule" in result["message"]

    def test_run_background_popen_failure(self) -> None:
        tool = RunBackgroundTool()
        with patch(
            "soothe_nano.toolkits.execution.subprocess.Popen",
            side_effect=OSError("spawn failed"),
        ):
            result = tool._run("sleep 1")
        assert result["status"] == "error"
        assert result["log_path"] is None
        assert "spawn failed" in result["message"]

    def test_run_background_passes_cwd_to_popen(self, tmp_path) -> None:
        tool = RunBackgroundTool(workspace_root=str(tmp_path))
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 12345

        def fake_popen(*_args, **kwargs):
            captured.update(kwargs)
            return FakeProc()

        with patch("soothe_nano.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
            result = tool._run("sleep 1")

        assert result["pid"] == 12345
        assert result["log_path"]
        assert captured.get("cwd") == str(tmp_path.resolve())
        assert captured.get("stdout") is not None

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

        with patch("soothe_nano.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
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

        with patch("soothe_nano.toolkits.execution.subprocess.Popen", side_effect=fake_popen):
            tool._run("sleep 1", runtime=runtime)

        assert captured.get("cwd") == str(client_ws.resolve())


class TestBackgroundLogDirResolution:
    def test_configured_log_dir_override(self, tmp_path) -> None:
        custom = tmp_path / "custom-logs"
        resolved = _resolve_background_log_dir(
            configured_dir=str(custom),
            workspace=str(tmp_path / "ws"),
            tool_runtime=None,
        )
        assert resolved == custom.resolve()
        assert custom.is_dir()

    def test_workspace_default_log_dir(self, tmp_path) -> None:
        ws = tmp_path / "project"
        ws.mkdir()
        resolved = _resolve_background_log_dir(
            configured_dir=None,
            workspace=str(ws),
            tool_runtime=None,
        )
        assert resolved == (ws / ".soothe" / "background").resolve()
        assert resolved.is_dir()


class TestExecutionToolkitConfig:
    def test_build_execution_toolkit_reads_background_log_dir(self) -> None:
        from types import SimpleNamespace

        from soothe_nano.toolkits.execution import build_execution_toolkit

        config = SimpleNamespace(
            security=None,
            tools=SimpleNamespace(
                execution=SimpleNamespace(
                    background_log_dir="/tmp/bg-logs",
                    background_log_retention_days=3,
                ),
            ),
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    tool_output=SimpleNamespace(code_exec_max_output_chars=32_000),
                ),
            ),
        )
        toolkit = build_execution_toolkit(config=config, workspace_root="/ws")
        bg_tool = next(t for t in toolkit.get_tools() if t.name == "run_background")
        kill_tool = next(t for t in toolkit.get_tools() if t.name == "kill_process")
        assert bg_tool.background_log_dir == "/tmp/bg-logs"
        assert bg_tool.background_log_retention_days == 3
        assert kill_tool.background_log_dir == "/tmp/bg-logs"
