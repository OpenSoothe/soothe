"""Extended unit tests for run_command output handling and subprocess wiring."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

from soothe_nano.toolkits.execution import (
    ExecutionToolkit,
    RunCommandShellTool,
    _execution_max_output_from_config,
)


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args="cmd", returncode=returncode, stdout=stdout, stderr="")


class TestRunCommandOutputCap:
    def test_execution_toolkit_passes_max_output_length(self) -> None:
        toolkit = ExecutionToolkit(max_output_length=500)
        run_command = next(t for t in toolkit.get_tools() if t.name == "run_command")
        assert run_command.max_output_length == 500

    def test_execution_max_output_from_config_default(self) -> None:
        assert _execution_max_output_from_config(None) == 100_000


class TestRunCommandOutputHandling:
    @staticmethod
    def _python_print_command(repeat_char: str, count: int) -> str:
        return f'"{sys.executable}" -c "print(\'{repeat_char}\' * {count})"'

    def test_strips_ansi_escape_sequences(self) -> None:
        tool = RunCommandShellTool(max_output_length=10_000)
        raw = "hello \x1b[31mworld\x1b[0m"
        with patch(
            "soothe_nano.toolkits.execution._run_shell_command_sync",
            return_value=_completed(raw),
        ):
            result = tool._run("echo test")
        assert "\x1b" not in result
        assert "hello world" in result

    def test_truncates_output_at_max_length(self) -> None:
        from soothe_nano.toolkits.execution import _run_shell_command_sync

        completed = _run_shell_command_sync(
            self._python_print_command("z", 5000),
            cwd=None,
            timeout=30,
            max_output_chars=200,
        )
        assert len(completed.stdout) <= 200 + len("\n... (output truncated)")
        assert completed.stdout.endswith("... (output truncated)")

    def test_run_command_tool_truncates_large_output(self) -> None:
        tool = RunCommandShellTool(max_output_length=200, timeout=30)
        result = tool._run(self._python_print_command("y", 10000))
        assert len(result) <= 200 + len("\n... (output truncated)")
        assert result.endswith("... (output truncated)")

    def test_per_call_timeout_forwarded(self) -> None:
        tool = RunCommandShellTool(timeout=60)
        with patch("soothe_nano.toolkits.execution._run_shell_command_sync") as mock_run:
            mock_run.return_value = _completed("ok")
            tool._run("sleep 1", timeout=5)
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["timeout"] == 5

    def test_max_output_chars_forwarded_to_sync_runner(self) -> None:
        tool = RunCommandShellTool(max_output_length=42)
        with patch("soothe_nano.toolkits.execution._run_shell_command_sync") as mock_run:
            mock_run.return_value = _completed("ok")
            tool._run("echo x")
        assert mock_run.call_args.kwargs["max_output_chars"] == 42

    def test_oserror_returns_error_string(self) -> None:
        tool = RunCommandShellTool()
        with patch(
            "soothe_nano.toolkits.execution._run_shell_command_sync",
            side_effect=OSError("bad fd"),
        ):
            result = tool._run("echo x")
        assert "Error executing command: bad fd" in result

    def test_nonzero_exit_still_returns_merged_stdout(self) -> None:
        tool = RunCommandShellTool()
        with patch(
            "soothe_nano.toolkits.execution._run_shell_command_sync",
            return_value=_completed("stderr merged\n", returncode=1),
        ):
            result = tool._run("false")
        assert "stderr merged" in result


class TestRunCommandWorkspaceWiring:
    def test_passes_resolved_cwd_to_subprocess(self, tmp_path) -> None:
        tool = RunCommandShellTool(workspace_root=str(tmp_path))
        with patch("soothe_nano.toolkits.execution._run_shell_command_sync") as mock_run:
            mock_run.return_value = _completed("")
            tool._run("pwd")
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path.resolve())

    def test_runtime_workspace_overrides_workspace_root(self, tmp_path) -> None:
        client = tmp_path / "client"
        client.mkdir()
        tool = RunCommandShellTool(workspace_root="/daemon")
        runtime = MagicMock()
        runtime.config = {"configurable": {"workspace": str(client)}}
        with patch("soothe_nano.toolkits.execution._run_shell_command_sync") as mock_run:
            mock_run.return_value = _completed("")
            tool._run("pwd", runtime=runtime)
        assert mock_run.call_args.kwargs["cwd"] == str(client.resolve())

    def test_virtual_path_translation_before_subprocess(self, tmp_path) -> None:
        security = MagicMock()
        security.allow_paths_outside_workspace = False
        tool = RunCommandShellTool(workspace_root=str(tmp_path), security_config=security)
        with patch("soothe_nano.toolkits.execution._run_shell_command_sync") as mock_run:
            mock_run.return_value = _completed("")
            tool._run("cat /notes.txt")
        cmd = mock_run.call_args.args[0]
        assert cmd == f"cat {tmp_path.resolve()}/notes.txt"
