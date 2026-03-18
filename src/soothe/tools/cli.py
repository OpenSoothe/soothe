"""Persistent CLI shell execution with security controls.

Ported from noesium's bash_toolkit.py for coding agent support.
Enhanced with regex banned patterns, shell recovery, and utility tools.
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)

# ANSI escape sequence pattern for cleaning shell output
ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Module-level storage for shell instances
_shell_instances: dict[str, Any] = {}


class CliTool(BaseTool):
    """Execute CLI commands in a persistent shell session.

    This tool provides a persistent shell where commands can maintain
    state (environment variables, working directory, etc.) across invocations.
    Includes security controls to prevent dangerous operations.
    """

    name: str = "run_cli"
    description: str = (
        "Execute a CLI command in a persistent shell session. "
        "Provide `command` (the command to run). "
        "The shell maintains state across commands (env vars, cwd, etc.). "
        "Returns the command output or error message."
    )

    workspace_root: str = Field(default="")
    timeout: int = Field(default=60)
    max_output_length: int = Field(default=10000)
    custom_prompt: str = Field(default="")

    # Security configuration - commands that are banned (substring match)
    banned_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "rm -rf ~",
            "rm -rf ./*",
            "rm -rf *",
            "mkfs",
            "dd if=",
            ":(){ :|:& };:",
            "sudo rm",
            "sudo dd",
            "chmod -R 777 /",
            "chown -R",
        ]
    )

    # Security configuration - regex patterns for banned commands
    banned_command_patterns: list[str] = Field(
        default_factory=lambda: [
            r"git\s+init",
            r"git\s+commit",
            r"git\s+add",
            r"rm\s+-rf\s+/",
            r"sudo\s+rm\s+-rf",
        ]
    )

    def __init__(self, **data: Any) -> None:
        """Initialize the CLI tool.

        Args:
            **data: Pydantic model fields (workspace_root, timeout, etc.).
        """
        super().__init__(**data)
        self._initialize_shell()

    def _initialize_shell(self) -> None:
        """Start persistent shell with custom prompt."""
        try:
            import pexpect

            custom_prompt = "soothe-cli>> "

            # Create shell instance
            child = pexpect.spawn(
                "/bin/bash",
                encoding="utf-8",
                echo=False,
                timeout=self.timeout,
            )

            # Set custom prompt for reliable output parsing
            child.sendline(f"PS1='{custom_prompt}'")
            child.expect(custom_prompt)

            # Set workspace directory if specified
            if self.workspace_root:
                workspace = str(Path(self.workspace_root).resolve())
                child.sendline(f"cd '{workspace}'")
                child.expect(custom_prompt)

            # Store instance at module level
            _shell_instances["default"] = child
            self.custom_prompt = custom_prompt

        except ImportError:
            logger.warning("pexpect not installed; cli tool will not work")
            self.custom_prompt = ""
        except Exception:
            logger.warning("Failed to initialize shell", exc_info=True)
            self.custom_prompt = ""

    def _is_banned(self, command: str) -> bool:
        """Check if command matches banned list or patterns."""
        # Check substring matches
        cmd_lower = command.strip().lower()
        if any(banned.lower() in cmd_lower for banned in self.banned_commands):
            return True

        # Check regex patterns
        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self.banned_command_patterns)

    def _test_shell_responsive(self) -> bool:
        """Test if shell is responsive."""
        try:
            child = _shell_instances.get("default")
            if not child:
                return False

            child.sendline("echo __test__")
            child.expect(self.custom_prompt)
            output = child.before or ""
        except Exception:
            return False
        else:
            return "__test__" in output

    def _recover_shell(self) -> None:
        """Recover the shell if it becomes unresponsive."""
        logger.warning("Attempting to recover shell...")
        with contextlib.suppress(Exception):
            if "default" in _shell_instances:
                with contextlib.suppress(Exception):
                    _shell_instances["default"].close()
                del _shell_instances["default"]

        self._initialize_shell()

        # Reset workspace if configured
        if self.workspace_root:
            workspace = str(Path(self.workspace_root).resolve())
            child = _shell_instances.get("default")
            if child:
                child.sendline(f"cd '{workspace}'")
                child.expect(self.custom_prompt)

        logger.info("Shell recovered successfully")

    def _run(self, command: str) -> str:
        """Execute CLI command with recovery support.

        Args:
            command: Command to execute.

        Returns:
            Command output or error message.
        """
        # Check if shell is available
        if "default" not in _shell_instances:
            return "Error: Shell not initialized. Install pexpect to use cli tool."

        # Security check
        if self._is_banned(command):
            logger.warning("Banned command attempted: %s", command)
            return "Error: Command not allowed for security reasons."

        try:
            # Test shell responsiveness
            if not self._test_shell_responsive():
                logger.warning("Shell not responsive, attempting recovery")
                self._recover_shell()

            # Execute command
            child = _shell_instances["default"]
            child.sendline(command)
            child.expect(self.custom_prompt)

            # Clean output
            output = child.before or ""

            # Remove ANSI escape sequences
            output = ANSI_ESCAPE.sub("", output)

            # Trim output if too long
            if len(output) > self.max_output_length:
                output = output[: self.max_output_length] + "\n... (output truncated)"

            return output.strip()

        except Exception as e:
            logger.exception("CLI command failed")
            # Attempt recovery for next command
            self._recover_shell()
            return f"Error executing command: {e}"

    async def _arun(self, command: str) -> str:
        """Async wrapper for sync execution."""
        return self._run(command)

    @classmethod
    def cleanup(cls) -> None:
        """Clean up shell resources."""
        if "default" in _shell_instances:
            with contextlib.suppress(Exception):
                _shell_instances["default"].close()
            del _shell_instances["default"]


class GetCurrentDirTool(BaseTool):
    """Get the current working directory."""

    name: str = "get_current_directory"
    description: str = "Get the current working directory of the persistent shell."

    def _run(self) -> str:
        """Get current working directory.

        Returns:
            Current directory path.
        """
        if "default" not in _shell_instances:
            return "Error: Shell not initialized."

        try:
            child = _shell_instances["default"]
            child.sendline("pwd")
            child.expect("soothe-cli>> ")
            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            return output.strip()
        except Exception as e:
            return f"Error: {e}"

    async def _arun(self) -> str:
        return self._run()


class ListDirTool(BaseTool):
    """List directory contents."""

    name: str = "list_directory"
    description: str = "List contents of a directory. Provide `path` (optional, defaults to current directory)."

    def _run(self, path: str = ".") -> str:
        """List directory contents.

        Args:
            path: Directory path to list (defaults to current directory).

        Returns:
            Directory listing or error message.
        """
        if "default" not in _shell_instances:
            return "Error: Shell not initialized."

        try:
            child = _shell_instances["default"]
            child.sendline(f"ls -la '{path}'")
            child.expect("soothe-cli>> ")
            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            return output.strip()
        except Exception as e:
            return f"Error: {e}"

    async def _arun(self, path: str = ".") -> str:
        return self._run(path)


class RunCliBackgroundTool(BaseTool):
    """Execute CLI commands in background."""

    name: str = "run_cli_background"
    description: str = (
        "Execute a CLI command in the background. "
        "Provide `command` (the command to run). "
        "Returns process ID for later management. "
        "Use for long-running commands."
    )

    def _run(self, command: str) -> str:
        """Execute command in background."""
        if "default" not in _shell_instances:
            return "Error: Shell not initialized."

        try:
            child = _shell_instances["default"]

            # Execute with nohup and &
            child.sendline(f"nohup {command} > /dev/null 2>&1 & echo $!")
            child.expect("soothe-cli>> ")

            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            pid = output.strip()

        except Exception as e:
            return f"Error starting background process: {e}"
        else:
            return f"Background process started with PID: {pid}"

    async def _arun(self, command: str) -> str:
        return self._run(command)


class KillProcessTool(BaseTool):
    """Terminate a background process."""

    name: str = "kill_process"
    description: str = "Terminate a background process. Provide `pid` (process ID from run_cli_background)."

    def _run(self, pid: str) -> str:
        """Kill process by PID."""
        if "default" not in _shell_instances:
            return "Error: Shell not initialized."

        try:
            child = _shell_instances["default"]
            child.sendline(f"kill {pid} 2>/dev/null || echo 'Process not found'")
            child.expect("soothe-cli>> ")

            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)

        except Exception as e:
            return f"Error killing process: {e}"
        else:
            if "Process not found" in output:
                return f"Process {pid} not found or already terminated"
            return f"Process {pid} terminated"

    async def _arun(self, pid: str) -> str:
        return self._run(pid)


class CheckCommandExistsTool(BaseTool):
    """Check if a command is available."""

    name: str = "check_command_exists"
    description: str = (
        "Check if a CLI command/tool is available on the system. Provide `command` (the command name to check)."
    )

    def _run(self, command: str) -> str:
        """Check if command exists."""
        if "default" not in _shell_instances:
            return "Error: Shell not initialized."

        try:
            child = _shell_instances["default"]
            child.sendline(f"which {command}")
            child.expect("soothe-cli>> ")

            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)

            if "not found" in output.lower() or not output.strip():
                return f"Command '{command}' not found"
            return f"Command '{command}' is available at: {output.strip()}"

        except Exception as e:
            return f"Error checking command: {e}"

    async def _arun(self, command: str) -> str:
        return self._run(command)


def create_cli_tools() -> list[BaseTool]:
    """Create CLI execution tools.

    Returns:
        List containing CLI tools:
        - run_cli: Execute CLI commands
        - get_current_directory: Get current working directory
        - list_directory: List directory contents
        - run_cli_background: Execute commands in background
        - kill_process: Terminate background processes
        - check_command_exists: Verify command availability
    """
    return [
        CliTool(),
        GetCurrentDirTool(),
        ListDirTool(),
        RunCliBackgroundTool(),
        KillProcessTool(),
        CheckCommandExistsTool(),
    ]
