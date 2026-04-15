"""Execution tools (RFC-0016 consolidation).

Consolidates single-purpose execution tools into one module:
- run_command: Execute shell commands synchronously
- run_python: Execute Python code with session persistence
- run_background: Run commands in background
- kill_process: Terminate background processes

Follows the pattern from image.py and audio.py.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from datetime import datetime
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe.utils import expand_path

from soothe.config.constants import DEFAULT_EXECUTE_TIMEOUT
from soothe.tools._internal.python_session_manager import get_session_manager
from soothe.tools._internal.shell import (
    ANSI_ESCAPE,
    ShellHealthState,
    _shell_health_states,
    _shell_instances,
)
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class RunCommandTool(BaseTool):
    """Execute a shell command synchronously.

    Use this tool for running CLI commands, system commands, and scripts.
    The command will execute and return output within the timeout period.
    For long-running commands (>60s), use run_background instead.
    """

    name: str = "run_command"
    description: str = (
        "Execute a shell command and return output. "
        "Use for: CLI tools, system commands, scripts. "
        "Parameters: command (required) - the shell command to run. "
        "Optional: timeout (default: 60 seconds). "
        "Returns: command output (stdout + stderr). "
        "For long-running commands (>60s), use run_background instead."
    )

    workspace_root: str = Field(default="", description="Working directory for shell")
    timeout: int = Field(default=DEFAULT_EXECUTE_TIMEOUT, description="Command timeout in seconds")
    max_output_length: int = Field(default=10000)
    custom_prompt: str = Field(default="")

    quick_timeout: int = Field(
        default=5, description="Timeout for quick operations (prompt detection, validation)"
    )
    responsiveness_timeout: int = Field(
        default=2, description="Timeout for shell responsiveness checks"
    )

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

    _shell_initialized: bool = False
    _last_workspace: str | None = None

    def __init__(self, **data: Any) -> None:
        """Initialize the CLI tool.

        Args:
            **data: Pydantic model fields (workspace_root, timeout, etc.).
        """
        super().__init__(**data)
        self._shell_initialized = False
        self._last_workspace = None
        self.custom_prompt = ""

    def _get_effective_workspace(self) -> str | None:
        """Get effective workspace, checking LangGraph config first (RFC-103).

        Priority:
        1. workspace from LangGraph configurable
        2. ContextVar (for same-async-context)
        3. self.workspace_root (static fallback)

        Returns:
            Effective workspace path or None.
        """
        # Priority 1: Try LangGraph configurable
        try:
            from langgraph.config import get_config

            config = get_config()
            configurable = config.get("configurable", {})
            workspace = configurable.get("workspace")
            if workspace:
                return str(workspace)
        except Exception:  # noqa: S110
            pass  # Not in LangGraph context - expected for non-LangGraph tool calls

        # Priority 2: Try ContextVar
        from soothe.core import FrameworkFilesystem

        dynamic_workspace = FrameworkFilesystem.get_current_workspace()
        if dynamic_workspace:
            return str(dynamic_workspace)

        # Priority 3: Use static fallback
        return self.workspace_root or None

    def _ensure_shell_initialized(self) -> None:
        """Lazy initialization guard - initializes shell on first use."""
        if not self._shell_initialized:
            self._initialize_shell()
            self._shell_initialized = True

    def _initialize_shell(self) -> None:
        """Start persistent shell with custom prompt (optimized)."""
        try:
            import pexpect

            custom_prompt = "soothe-cli>> "
            init_timeout = 2  # Reduced from default 5s for faster initialization

            child = pexpect.spawn(
                "/bin/bash",
                encoding="utf-8",
                echo=False,
                timeout=self.timeout,
            )

            # Send all setup commands in one batch (eliminates unnecessary sleeps)
            # stty -onlcr: disable newline-to-carriage-return mapping
            # unset PROMPT_COMMAND: clear any existing prompt hooks
            # PS1 setup: set custom prompt marker
            # echo '__init__': validation marker to confirm initialization
            child.sendline(
                "stty -onlcr; unset PROMPT_COMMAND; PS1='soothe-cli>> '; echo '__init__'"
            )

            # Single expect operation for all setup (was 5 separate expects before)
            child.expect(custom_prompt, timeout=init_timeout)
            output = child.before or ""

            # Validate initialization marker
            if "__init__" not in output:
                msg = f"Shell initialization failed. Expected '__init__' in output, got: {preview_first(output, 100)}"
                raise RuntimeError(msg)

            # Set working directory if specified
            if self.workspace_root:
                workspace = str(expand_path(self.workspace_root))
                child.sendline(f"cd '{workspace}'")
                child.expect(custom_prompt, timeout=init_timeout)

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

        return any(
            re.search(pattern, command, re.IGNORECASE) for pattern in self.banned_command_patterns
        )

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

                logger.warning(
                    "Shell test attempt %d failed: unexpected output '%s'",
                    attempt + 1,
                    preview_first(output, 50),
                )

            except pexpect.TIMEOUT:
                logger.warning(
                    "Shell test attempt %d timed out after %ds",
                    attempt + 1,
                    self.responsiveness_timeout,
                )
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
            logger.debug(
                "Testing responsiveness: trouble sign detected (%s)", health.last_trouble_sign
            )
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

    def _run(self, command: str, timeout: int | None = None) -> str:
        """Execute shell command synchronously.

        Args:
            command: Shell command to execute
            timeout: Optional timeout override (uses instance default if not provided)

        Returns:
            Combined stdout and stderr output

        Raises:
            TimeoutError: If command exceeds timeout
            FileNotFoundError: If command not found (handled internally)
        """
        self._ensure_shell_initialized()

        if "default" not in _shell_instances:
            return "Error: Shell not initialized. Install pexpect: pip install pexpect"

        import pexpect

        if self._is_banned(command):
            logger.warning("Banned command attempted: %s", command)
            return "Error: Command not allowed for security reasons."

        # Get dynamic workspace and change to it before running command (RFC-103)
        effective_workspace = self._get_effective_workspace()
        if effective_workspace and effective_workspace != self._last_workspace:
            child = _shell_instances.get("default")
            if child:
                child.sendline(f"cd '{effective_workspace}'")
                child.expect(self.custom_prompt, timeout=self.quick_timeout)
                self._last_workspace = effective_workspace
                logger.debug("Changed to workspace: %s", effective_workspace)

        # Use provided timeout or fall back to instance default
        actual_timeout = timeout if timeout is not None else self.timeout

        health = _shell_health_states.get("default")
        if health is None:
            health = ShellHealthState()
            _shell_health_states["default"] = health

        start_time = time.time()
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
                child.expect(self.custom_prompt, timeout=actual_timeout)
            except pexpect.TIMEOUT:
                trouble_sign = self._detect_trouble_sign(
                    error=TimeoutError(f"Timeout after {actual_timeout}s")
                )
                health.last_command_success = False
                health.last_command_timestamp = datetime.now()
                health.consecutive_failures += 1
                health.last_trouble_sign = trouble_sign
                health.first_command_executed = True

                return (
                    f"Error: Command timed out after {actual_timeout}s. "
                    f"For long-running operations, use run_background instead, "
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
            _ = int((time.time() - start_time) * 1000)  # Duration tracking
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
            _ = int((time.time() - start_time) * 1000)  # Duration tracking
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

    async def _arun(self, command: str, timeout: int | None = None) -> str:  # noqa: ASYNC109
        """Async execution (delegates to sync).

        Args:
            command: Shell command to execute
            timeout: Optional timeout override (uses instance default if not provided)
        """
        return self._run(command, timeout)

    @classmethod
    def cleanup(cls) -> None:
        """Cleanup shell instances and health states."""
        from soothe.tools._internal.shell import cleanup_shell

        cleanup_shell("default")


class RunPythonTool(BaseTool):
    r"""Execute Python code with session persistence.

    Use this tool for data analysis, calculations, and Python scripting.
    Variables persist across calls within the same thread, enabling iterative
    workflows like loading data and then analyzing it in subsequent calls.

    Example:
        Call 1: run_python(code="import pandas as pd\\ndf = pd.read_csv('data.csv')")
        Call 2: run_python(code="df.head()")  # Works! df persists
        Call 3: run_python(code="df.groupby('category').sum()")  # Continue analysis
    """

    name: str = "run_python"
    description: str = (
        "Execute Python code with session persistence. "
        "Variables persist across calls within the same thread. "
        "Use for: data analysis, calculations, Python scripting. "
        "Parameters: code (required) - Python code to execute. "
        "Returns: execution result, output, or error."
    )

    workdir: str = Field(default="", description="Working directory")
    timeout: int = Field(default=30, description="Execution timeout in seconds")
    session_id: str | None = Field(
        default=None, description="Session ID for persistence (default: auto-detected from thread)"
    )

    def _run(self, code: str, session_id: str | None = None) -> dict[str, Any]:
        """Execute Python code in persistent session.

        Args:
            code: Python code to execute
            session_id: Session identifier (default: thread_id from context or self.session_id)

        Returns:
            Dict with 'success', 'output', 'result', 'error'
        """
        # Use provided session_id or try to get from instance
        actual_session_id = session_id or self.session_id

        if actual_session_id is None:
            # Default session ID
            actual_session_id = "default"

        # Get session manager and execute
        manager = get_session_manager()
        return manager.execute(session_id=actual_session_id, code=code)

    async def _arun(self, code: str, session_id: str | None = None) -> dict[str, Any]:
        """Async execution (delegates to sync)."""
        return self._run(code, session_id)


class RunBackgroundTool(BaseTool):
    """Run a long-running command in the background.

    Use this tool for commands that take a long time or need to continue
    running while you do other tasks. The command will execute in the
    background and you'll receive a process ID for tracking.
    """

    name: str = "run_background"
    description: str = (
        "Run a long-running command in the background. "
        "Use for: training scripts, servers, long computations. "
        "Parameters: command (required) - the command to run. "
        "Returns: process ID for tracking. "
        "Use kill_process to stop background commands."
    )

    def _run(self, command: str) -> dict[str, Any]:
        """Execute command in background process.

        Args:
            command: Command to run in background

        Returns:
            Dict with 'pid', 'status', and 'message'
        """
        if "default" not in _shell_instances:
            return {"pid": None, "status": "error", "message": "Error: Shell not initialized."}

        try:
            child = _shell_instances["default"]
            child.sendline(f"nohup {command} > /dev/null 2>&1 & echo $!")
            child.expect("soothe-cli>> ")

            output = child.before or ""
            output = ANSI_ESCAPE.sub("", output)
            pid = output.strip()

            pid_int = int(pid)
        except Exception as e:
            return {
                "pid": None,
                "status": "error",
                "message": f"Error starting background process: {e}",
            }
        else:
            return {
                "pid": pid_int,
                "status": "running",
                "message": f"Background process started with PID: {pid}",
            }

    async def _arun(self, command: str) -> dict[str, Any]:
        """Async execution (delegates to sync)."""
        return self._run(command)


class KillProcessTool(BaseTool):
    """Terminate a background process.

    Use this tool to stop a command that was started with run_background.
    You need the process ID (PID) that was returned when you started the command.
    """

    name: str = "kill_process"
    description: str = (
        "Terminate a background process. "
        "Parameters: pid (required) - process ID from run_background. "
        "Returns: termination status."
    )

    def _run(self, pid: int) -> str:
        """Terminate background process.

        Args:
            pid: Process ID to terminate

        Returns:
            Status message
        """
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

    async def _arun(self, pid: int) -> str:
        """Async execution (delegates to sync)."""
        return self._run(pid)


def create_execution_tools(
    *,
    workspace_root: str = "",
    timeout: int = 60,
) -> list[BaseTool]:
    """Create all execution tools.

    Args:
        workspace_root: Working directory for shell sessions.
        timeout: Default timeout for shell commands.

    Returns:
        List of execution BaseTool instances.
    """
    return [
        RunCommandTool(workspace_root=workspace_root, timeout=timeout),
        RunPythonTool(workdir=workspace_root),
        RunBackgroundTool(),
        KillProcessTool(),
    ]
