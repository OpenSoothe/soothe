"""Unified execution tool for shell and Python code (RFC-0014).

Consolidates cli tools (run_cli, run_cli_background, kill_process,
get_current_directory, check_command_exists) and python_executor into
a single mode-dispatched tool.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)

_KILL_PATTERN = re.compile(r"^kill\s+(\d+)\s*$", re.IGNORECASE)


class ExecuteTool(BaseTool):
    """Run shell commands, Python code, or background processes.

    Modes: shell, python, background.
    """

    name: str = "execute"
    description: str = (
        "Run commands or code. "
        "Provide `code` (the command or code to run) and `mode`.\n"
        "Modes:\n"
        "- 'shell': Execute a CLI command in a persistent shell session. "
        "The shell maintains state (env vars, cwd) across calls.\n"
        "- 'python': Execute Python code. Supports matplotlib (plots saved as PNG). "
        "Returns stdout, stderr, result, and created files.\n"
        "- 'background': Start a long-running command in the background. "
        "Returns the process ID.\n"
        "Special: In shell mode, `kill <pid>` terminates a background process."
    )

    workspace_root: str = Field(default="")

    def _run(self, code: str, mode: str = "shell", **_kwargs: Any) -> str:
        """Execute code in the specified mode.

        Args:
            code: Command or code to run.
            mode: One of 'shell', 'python', 'background'.

        Returns:
            Execution output or error message.
        """
        mode = mode.strip().lower()

        if mode == "python":
            return self._do_python(code)
        if mode == "background":
            return self._do_background(code)
        if mode == "shell":
            return self._do_shell(code)

        return f"Error: Unknown mode '{mode}'. Use: shell, python, background."

    async def _arun(self, code: str, mode: str = "shell", **kwargs: Any) -> str:
        """Async execution (delegates to sync)."""
        return self._run(code, mode, **kwargs)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _do_shell(self, command: str) -> str:
        kill_match = _KILL_PATTERN.match(command.strip())
        if kill_match:
            return self._do_kill(kill_match.group(1))

        from soothe.tools._internal.cli.tools import CliTool

        tool = CliTool(workspace_root=self.workspace_root)
        return tool._run(command)

    def _do_python(self, code: str) -> str:
        from soothe.tools._internal.python_executor import PythonExecutorTool

        tool = PythonExecutorTool(workdir=self.workspace_root)
        result = tool._run(code)
        if isinstance(result, dict):
            parts = []
            if result.get("stdout"):
                parts.append(result["stdout"])
            if result.get("stderr"):
                parts.append(f"STDERR: {result['stderr']}")
            if result.get("result"):
                parts.append(f"Result: {result['result']}")
            if result.get("error"):
                parts.append(f"Error: {result['error']}")
            if result.get("files"):
                parts.append(f"Files created: {', '.join(result['files'])}")
            return "\n".join(parts) if parts else "Code executed successfully (no output)."
        return str(result)

    def _do_background(self, command: str) -> str:
        from soothe.tools._internal.cli.tools import RunCliBackgroundTool

        tool = RunCliBackgroundTool()
        return tool._run(command)

    def _do_kill(self, pid: str) -> str:
        from soothe.tools._internal.cli.tools import KillProcessTool

        tool = KillProcessTool()
        return tool._run(pid)


def create_execute_tools(*, workspace_root: str = "") -> list[BaseTool]:
    """Create the unified execute tool.

    Args:
        workspace_root: Working directory for shell sessions.

    Returns:
        List containing a single ExecuteTool.
    """
    return [ExecuteTool(workspace_root=workspace_root)]
