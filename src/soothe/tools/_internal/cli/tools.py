"""CLI tool classes for persistent shell execution."""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import datetime
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.tools._internal.cli.shell import (
    ANSI_ESCAPE,
    ShellHealthState,
    _shell_health_states,
    _shell_instances,
)
from soothe.utils import expand_path

logger = logging.getLogger(__name__)


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

    quick_timeout: int = Field(default=5, description="Timeout for quick operations (prompt detection, validation)")
    responsiveness_timeout: int = Field(default=2, description="Timeout for shell responsiveness checks")

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
        self._shell_initialized = False
        self.custom_prompt = ""

    def _ensure_shell_initialized(self) -> None:
        """Lazy initialization guard - initializes shell on first use."""
        if not self._shell_initialized:
            self._initialize_shell()
            self._shell_initialized = True

    def _initialize_shell(self) -> None:
        """Start persistent shell with custom prompt."""
        try:
            import time

            import pexpect

            custom_prompt = "soothe-cli>> "

            child = pexpect.spawn(
                "/bin/bash",
                encoding="utf-8",
                echo=False,
                timeout=self.timeout,
            )

            child.sendline("stty -onlcr")
            time.sleep(0.1)

            child.sendline("unset PROMPT_COMMAND")
            time.sleep(0.1)

            child.sendline(f"PS1='{custom_prompt}'")
            child.expect(custom_prompt, timeout=self.quick_timeout)

            child.sendline("echo '__buffer_clear__'")
            child.expect(custom_prompt, timeout=self.quick_timeout)

            child.sendline("echo '__validation__'")
            child.expect(custom_prompt, timeout=self.quick_timeout)
            output = child.before or ""

            if "__validation__" not in output:
                msg = f"Shell prompt validation failed. Expected '__validation__' in output, got: {output[:100]}"
                raise RuntimeError(msg)

            if self.workspace_root:
                workspace = str(expand_path(self.workspace_root))
                child.sendline(f"cd '{workspace}'")
                child.expect(custom_prompt, timeout=self.quick_timeout)

            _shell_instances["default"] = child
            self.custom_prompt = custom_prompt

            logger.info("Shell initialized successfully")

        except ImportError:
            logger.warning("pexpect not installed; cli tool will not work")
            self.custom_prompt = ""

        except Exception:
            logger.exception("Failed to initialize shell")
            self.custom_prompt = ""

            if "child" in locals():
                with contextlib.suppress(Exception):
                    child.close()

    def _is_banned(self, command: str) -> bool:
        """Check if command matches banned list or patterns."""
        cmd_lower = command.strip().lower()
        if any(banned.lower() in cmd_lower for banned in self.banned_commands):
            return True

        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self.banned_command_patterns)

    def _test_shell_responsive(self, max_attempts: int = 2) -> bool:
        """Test if shell is responsive with quick timeout.

        Args:
            max_attempts: Number of test attempts (default: 2)

        Returns:
            True if shell responds correctly, False otherwise
        """
        import time

        import pexpect

        child = _shell_instances.get("default")
        if not child:
            return False

        for attempt in range(max_attempts):
            try:
                child.sendline("echo __test__")
                child.expect(self.custom_prompt, timeout=self.responsiveness_timeout)
                output = child.before or ""

                if "__test__" in output:
                    logger.debug("Shell responsiveness test passed (attempt %d)", attempt + 1)
                    return True

                logger.warning("Shell test attempt %d failed: unexpected output '%s'", attempt + 1, output[:50])

            except pexpect.TIMEOUT:
                logger.warning("Shell test attempt %d timed out after %ds", attempt + 1, self.responsiveness_timeout)
            except Exception as e:
                logger.warning("Shell test attempt %d failed: %s", attempt + 1, e)

            if attempt < max_attempts - 1:
                time.sleep(0.5)

        logger.error("Shell responsiveness test failed after all attempts")
        return False

    def _should_test_responsiveness(self, shell_id: str = "default") -> bool:
        """Determine if responsiveness test is needed based on shell health.

        Args:
            shell_id: Shell identifier (default: "default")

        Returns:
            True if test should be performed, False to skip
        """
        health = _shell_health_states.get(shell_id)

        if health is None:
            logger.debug("Testing responsiveness: first command")
            return True

        if health.shell_recovered:
            logger.debug("Testing responsiveness: shell was recovered")
            return True

        if not health.first_command_executed:
            logger.debug("Testing responsiveness: validating initialization")
            return True

        if not health.last_command_success:
            logger.debug("Testing responsiveness: previous command failed")
            return True

        consecutive_failure_threshold = 2
        if health.consecutive_failures >= consecutive_failure_threshold:
            logger.debug("Testing responsiveness: consecutive failures detected")
            return True

        if health.last_trouble_sign != "none":
            logger.debug("Testing responsiveness: trouble sign detected (%s)", health.last_trouble_sign)
            return True

        logger.debug("Skipping responsiveness test: shell healthy")
        return False

    def _detect_trouble_sign(
        self, error: Exception | None = None, _output: str = ""
    ) -> Literal["timeout", "eof", "error", "unexpected_output", "none"]:
        """Detect trouble signs from command execution.

        Args:
            error: Exception that occurred during execution (if any)
            _output: Command output (if any)

        Returns:
            Type of trouble sign detected, or "none" if healthy
        """
        import pexpect

        if error is None:
            return "none"

        if isinstance(error, pexpect.TIMEOUT):
            return "timeout"
        if isinstance(error, pexpect.EOF):
            return "eof"
        if isinstance(error, Exception):
            return "error"

        return "none"

    def _recover_shell(self, max_retries: int = 2) -> None:
        """Recover the shell if it becomes unresponsive.

        Args:
            max_retries: Number of recovery attempts (default: 2)

        Raises:
            RuntimeError: If all recovery attempts fail
        """
        import time

        logger.warning("Attempting to recover shell...")

        for attempt in range(max_retries):
            try:
                with contextlib.suppress(Exception):
                    if "default" in _shell_instances:
                        with contextlib.suppress(Exception):
                            _shell_instances["default"].close()
                        del _shell_instances["default"]

                self._initialize_shell()

                if not self._test_shell_responsive():
                    raise RuntimeError("Recovered shell failed responsiveness test")

                if self.workspace_root:
                    workspace = str(expand_path(self.workspace_root))
                    child = _shell_instances.get("default")
                    if child:
                        child.sendline(f"cd '{workspace}'")
                        child.expect(self.custom_prompt, timeout=self.quick_timeout)

                logger.info("Shell recovered successfully (attempt %d)", attempt + 1)

            except Exception as e:
                logger.exception("Recovery attempt %d failed", attempt + 1)

                if attempt < max_retries - 1:
                    logger.info("Retrying recovery...")
                    time.sleep(1)
                else:
                    logger.exception("All recovery attempts failed")
                    msg = f"Shell recovery failed after {max_retries} attempts: {e}"
                    raise RuntimeError(msg) from e

    def _run(self, command: str) -> str:
        """Execute CLI command with recovery support.

        Args:
            command: Command to execute

        Returns:
            Command output (stripped, ANSI-cleaned) or error message
        """
        self._ensure_shell_initialized()

        if "default" not in _shell_instances:
            return "Error: Shell not initialized. Install pexpect: pip install pexpect"

        import pexpect

        if self._is_banned(command):
            logger.warning("Banned command attempted: %s", command)
            return "Error: Command not allowed for security reasons."

        health = _shell_health_states.get("default")
        if health is None:
            health = ShellHealthState()
            _shell_health_states["default"] = health

        try:
            if self._should_test_responsiveness("default"):
                if not self._test_shell_responsive():
                    logger.warning("Shell not responsive, attempting recovery")
                    try:
                        self._recover_shell()
                        health.shell_recovered = True
                    except RuntimeError as e:
                        return f"Error: Shell recovery failed. Please restart the application. Details: {e}"
            else:
                health.shell_recovered = False

            child = _shell_instances["default"]
            child.sendline(command)

            try:
                child.expect(self.custom_prompt, timeout=self.timeout)
            except pexpect.TIMEOUT:
                trouble_sign = self._detect_trouble_sign(error=TimeoutError(f"Timeout after {self.timeout}s"))
                health.last_command_success = False
                health.last_command_timestamp = datetime.now()
                health.consecutive_failures += 1
                health.last_trouble_sign = trouble_sign
                health.first_command_executed = True

                return (
                    f"Error: Command timed out after {self.timeout}s. "
                    f"For long-running operations, use run_cli_background instead, "
                    f"or increase the timeout configuration."
                )

            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)

            if len(output) > self.max_output_length:
                output = output[: self.max_output_length] + "\n... (output truncated)"

            health.last_command_success = True
            health.last_command_timestamp = datetime.now()
            health.consecutive_failures = 0
            health.last_trouble_sign = "none"
            health.first_command_executed = True

            return output.strip()

        except pexpect.EOF as e:
            logger.exception("Shell process terminated unexpectedly")
            trouble_sign = self._detect_trouble_sign(error=e)
            health.last_command_success = False
            health.last_command_timestamp = datetime.now()
            health.consecutive_failures += 1
            health.last_trouble_sign = trouble_sign

            self._recover_shell()
            health.shell_recovered = True
            return "Error: Shell terminated unexpectedly. Shell has been restarted. Please retry your command."

        except Exception as e:
            logger.exception("CLI command failed")
            trouble_sign = self._detect_trouble_sign(error=e)
            health.last_command_success = False
            health.last_command_timestamp = datetime.now()
            health.consecutive_failures += 1
            health.last_trouble_sign = trouble_sign

            with contextlib.suppress(Exception):
                self._recover_shell()
                health.shell_recovered = True
            return f"Error executing command: {e}"

    async def _arun(self, command: str) -> str:
        """Async wrapper for sync execution."""
        return self._run(command)

    @classmethod
    def cleanup(cls) -> None:
        """Clean up shell resources and health states."""
        from soothe.tools._internal.cli.shell import cleanup_shell

        cleanup_shell("default")


class GetCurrentDirTool(BaseTool):
    """Get the current working directory."""

    name: str = "get_current_directory"
    description: str = "Get the current working directory of the persistent shell."

    def _run(self) -> str:
        """Get current working directory."""
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
