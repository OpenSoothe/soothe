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

    # Tiered timeout system
    quick_timeout: int = Field(default=5, description="Timeout for quick operations (prompt detection, validation)")
    responsiveness_timeout: int = Field(default=2, description="Timeout for shell responsiveness checks")

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
        """Start persistent shell with custom prompt.

        Invariants:
        - Shell prompt MUST be "soothe-cli>> " and reliably detectable
        - Shell MUST be responsive after this method completes
        - If initialization fails, shell MUST be cleaned up
        """
        try:
            import pexpect
            import time

            custom_prompt = "soothe-cli>> "

            # STEP 1: Create shell instance
            child = pexpect.spawn(
                "/bin/bash",
                encoding="utf-8",
                echo=False,
                timeout=self.timeout,
            )

            # STEP 2: Disable newline conversion
            # Rationale: Prevents \r\n issues that break prompt matching
            child.sendline("stty -onlcr")
            time.sleep(0.1)  # Allow command to execute

            # STEP 3: Clear PROMPT_COMMAND
            # Rationale: User's bashrc may set this, overriding PS1
            child.sendline("unset PROMPT_COMMAND")
            time.sleep(0.1)

            # STEP 4: Set custom prompt
            child.sendline(f"PS1='{custom_prompt}'")

            # STEP 5: Wait for prompt (validation)
            # Uses quick_timeout (5s) instead of full timeout
            child.expect(custom_prompt, timeout=self.quick_timeout)

            # STEP 6: Verify prompt is working
            child.sendline("echo '__validation__'")
            child.expect(custom_prompt, timeout=self.quick_timeout)
            output = child.before or ""

            if "__validation__" not in output:
                raise RuntimeError(
                    f"Shell prompt validation failed. Expected '__validation__' in output, got: {output[:100]}"
                )

            # STEP 7: Set workspace if configured
            if self.workspace_root:
                workspace = str(Path(self.workspace_root).resolve())
                child.sendline(f"cd '{workspace}'")
                child.expect(custom_prompt, timeout=self.quick_timeout)

            # STEP 8: Store instance
            _shell_instances["default"] = child
            self.custom_prompt = custom_prompt

            logger.info("Shell initialized successfully")

        except ImportError:
            logger.warning("pexpect not installed; cli tool will not work")
            self.custom_prompt = ""

        except Exception as e:
            logger.error(f"Failed to initialize shell: {e}", exc_info=True)
            self.custom_prompt = ""

            # Clean up partial initialization
            if "child" in locals():
                with contextlib.suppress(Exception):
                    child.close()

    def _is_banned(self, command: str) -> bool:
        """Check if command matches banned list or patterns."""
        # Check substring matches
        cmd_lower = command.strip().lower()
        if any(banned.lower() in cmd_lower for banned in self.banned_commands):
            return True

        # Check regex patterns
        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self.banned_command_patterns)

    def _test_shell_responsive(self, max_attempts: int = 2) -> bool:
        """Test if shell is responsive with quick timeout.

        Uses short timeout to avoid blocking on unresponsive shells.
        Retries once before declaring failure.

        Args:
            max_attempts: Number of test attempts (default: 2)

        Returns:
            True if shell responds correctly, False otherwise

        Invariants:
        - MUST complete in <5 seconds (2 attempts × 2s timeout + sleep)
        - MUST NOT raise exceptions (returns bool only)
        - MUST NOT modify shell state on failure
        """
        import pexpect
        import time

        child = _shell_instances.get("default")
        if not child:
            return False

        for attempt in range(max_attempts):
            try:
                # Use short timeout for responsiveness check
                child.sendline("echo __test__")
                child.expect(self.custom_prompt, timeout=self.responsiveness_timeout)
                output = child.before or ""

                if "__test__" in output:
                    logger.debug(f"Shell responsiveness test passed (attempt {attempt + 1})")
                    return True

                logger.warning(f"Shell test attempt {attempt + 1} failed: unexpected output '{output[:50]}'")

            except pexpect.TIMEOUT:
                logger.warning(f"Shell test attempt {attempt + 1} timed out after {self.responsiveness_timeout}s")
            except Exception as e:
                logger.warning(f"Shell test attempt {attempt + 1} failed: {e}")

            # Brief pause before retry
            if attempt < max_attempts - 1:
                time.sleep(0.5)

        logger.error("Shell responsiveness test failed after all attempts")
        return False

    def _recover_shell(self, max_retries: int = 2) -> None:
        """Recover the shell if it becomes unresponsive.

        Cleans up existing shell, reinitializes, and validates.
        Retries if first attempt fails.

        Args:
            max_retries: Number of recovery attempts (default: 2)

        Raises:
            RuntimeError: If all recovery attempts fail

        Invariants:
        - Old shell MUST be cleaned up (no zombie processes)
        - New shell MUST pass responsiveness test
        - Workspace directory MUST be restored if configured
        """
        import time

        logger.warning("Attempting to recover shell...")

        for attempt in range(max_retries):
            try:
                # STEP 1: Cleanup existing shell
                with contextlib.suppress(Exception):
                    if "default" in _shell_instances:
                        with contextlib.suppress(Exception):
                            _shell_instances["default"].close()
                        del _shell_instances["default"]

                # STEP 2: Re-initialize
                self._initialize_shell()

                # STEP 3: Validate new shell works
                if not self._test_shell_responsive():
                    raise RuntimeError("Recovered shell failed responsiveness test")

                # STEP 4: Reset workspace
                if self.workspace_root:
                    workspace = str(Path(self.workspace_root).resolve())
                    child = _shell_instances.get("default")
                    if child:
                        child.sendline(f"cd '{workspace}'")
                        child.expect(self.custom_prompt, timeout=self.quick_timeout)

                logger.info(f"Shell recovered successfully (attempt {attempt + 1})")
                return

            except Exception as e:
                logger.error(f"Recovery attempt {attempt + 1} failed: {e}")

                if attempt < max_retries - 1:
                    logger.info("Retrying recovery...")
                    time.sleep(1)
                else:
                    logger.error("All recovery attempts failed")
                    raise RuntimeError(f"Shell recovery failed after {max_retries} attempts: {e}") from e

    def _run(self, command: str) -> str:
        """Execute CLI command with recovery support.

        Args:
            command: Command to execute

        Returns:
            Command output (stripped, ANSI-cleaned) or error message

        Invariants:
        - MUST check shell responsiveness before execution
        - MUST attempt recovery if shell unresponsive
        - MUST return clear, actionable error messages
        - MUST NOT leave shell in inconsistent state
        """
        import pexpect

        # Pre-checks
        if "default" not in _shell_instances:
            return "Error: Shell not initialized. Install pexpect: pip install pexpect"

        if self._is_banned(command):
            logger.warning("Banned command attempted: %s", command)
            return "Error: Command not allowed for security reasons."

        try:
            # Test responsiveness
            if not self._test_shell_responsive():
                logger.warning("Shell not responsive, attempting recovery")
                try:
                    self._recover_shell()
                except RuntimeError as e:
                    return f"Error: Shell recovery failed. Please restart the application. Details: {e}"

            # Execute command
            child = _shell_instances["default"]
            child.sendline(command)

            # Specific timeout handling
            try:
                child.expect(self.custom_prompt, timeout=self.timeout)
            except pexpect.TIMEOUT:
                return (
                    f"Error: Command timed out after {self.timeout}s. "
                    f"For long-running operations, use run_cli_background instead, "
                    f"or increase the timeout configuration."
                )

            # Process output
            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)

            if len(output) > self.max_output_length:
                output = output[: self.max_output_length] + "\n... (output truncated)"

            return output.strip()

        except pexpect.EOF:
            logger.exception("Shell process terminated unexpectedly")
            self._recover_shell()
            return "Error: Shell terminated unexpectedly. Shell has been restarted. Please retry your command."

        except Exception as e:
            logger.exception("CLI command failed")
            with contextlib.suppress(Exception):
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
