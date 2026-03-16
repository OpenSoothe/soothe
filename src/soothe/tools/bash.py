"""Persistent bash shell execution with security controls.

Ported from noesium's bash_toolkit.py for coding agent support.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, ClassVar

from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)

# ANSI escape sequence pattern for cleaning shell output
ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Module-level storage for shell instances
_shell_instances: dict[str, Any] = {}


class BashTool(BaseTool):
    """Execute bash commands in a persistent shell session.

    This tool provides a persistent bash shell where commands can maintain
    state (environment variables, working directory, etc.) across invocations.
    Includes security controls to prevent dangerous operations.
    """

    name: str = "run_bash"
    description: str = (
        "Execute a bash command in a persistent shell session. "
        "Provide `command` (the bash command to run). "
        "The shell maintains state across commands (env vars, cwd, etc.). "
        "Returns the command output or error message."
    )

    workspace_root: str = Field(default="")
    timeout: int = Field(default=60)
    max_output_length: int = Field(default=10000)
    custom_prompt: str = Field(default="")

    # Security configuration - commands that are banned
    banned_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "rm -rf ~",
            "mkfs",
            "dd if=",
            ":(){ :|:& };:",
            "chmod -R 777 /",
            "chown -R",
        ]
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._initialize_shell()

    def _initialize_shell(self) -> None:
        """Start persistent bash shell with custom prompt."""
        try:
            import pexpect

            custom_prompt = "soothe-bash>> "

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
                workspace = os.path.abspath(self.workspace_root)
                child.sendline(f"cd '{workspace}'")
                child.expect(custom_prompt)

            # Store instance at module level
            _shell_instances["default"] = child
            self.custom_prompt = custom_prompt

        except ImportError:
            logger.warning("pexpect not installed; bash tool will not work")
            self.custom_prompt = ""
        except Exception:  # noqa: BLE001
            logger.warning("Failed to initialize bash shell", exc_info=True)
            self.custom_prompt = ""

    def _is_banned(self, command: str) -> bool:
        """Check if command is in banned list."""
        cmd_lower = command.strip().lower()
        for banned in self.banned_commands:
            if banned.lower() in cmd_lower:
                return True
        return False

    def _run(self, command: str) -> str:
        """Execute bash command in persistent shell.

        Args:
            command: Bash command to execute.

        Returns:
            Command output or error message.
        """
        # Check if shell is available
        if "default" not in _shell_instances:
            return "Error: Shell not initialized. Install pexpect to use bash tool."

        # Security check
        if self._is_banned(command):
            logger.warning("Banned command attempted: %s", command)
            return "Error: Command not allowed for security reasons."

        try:
            child = _shell_instances["default"]

            # Execute command
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

        except Exception as e:  # noqa: BLE001
            logger.error("Bash command failed: %s", e, exc_info=True)
            # Try to reinitialize shell on error
            self._initialize_shell()
            return f"Error executing command: {e}"

    async def _arun(self, command: str) -> str:
        """Async wrapper for sync execution."""
        return self._run(command)


class GetCurrentDirTool(BaseTool):
    """Get the current working directory."""

    name: str = "get_current_directory"
    description: str = "Get the current working directory of the persistent bash shell."

    def _run(self) -> str:
        """Get current working directory.

        Returns:
            Current directory path.
        """
        if "default" not in BashTool._shell_instance:
            return "Error: Shell not initialized."

        try:
            child = BashTool._shell_instance["default"]
            child.sendline("pwd")
            child.expect("soothe-bash>> ")
            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            return output.strip()
        except Exception as e:  # noqa: BLE001
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
        if "default" not in BashTool._shell_instance:
            return "Error: Shell not initialized."

        try:
            child = BashTool._shell_instance["default"]
            child.sendline(f"ls -la '{path}'")
            child.expect("soothe-bash>> ")
            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            return output.strip()
        except Exception as e:  # noqa: BLE001
            return f"Error: {e}"

    async def _arun(self, path: str = ".") -> str:
        return self._run(path)


def create_bash_tools() -> list[BaseTool]:
    """Create bash execution tools.

    Returns:
        List containing bash tools: run_bash, get_current_directory, list_directory.
    """
    return [
        BashTool(),
        GetCurrentDirTool(),
        ListDirTool(),
    ]
