"""Execution tools (RFC-0016 consolidation).

Consolidates single-purpose execution tools into one module:
- run_command: Execute shell commands synchronously (langchain_community ShellTool)
- run_python: Execute Python code (langchain_experimental PythonREPLTool)
- run_background: Run commands in background
- kill_process: Terminate background processes

Follows the pattern from image.py and audio.py.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from langchain_community.tools import ShellTool
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables.config import run_in_executor
from langchain_core.tools import BaseTool
from langchain_core.tools.base import InjectedToolArg
from langchain_experimental.tools.python.tool import PythonREPLTool, sanitize_input
from langchain_experimental.utilities.python import PythonREPL

try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at static analysis time
    ToolRuntime = Any  # type: ignore[misc,assignment]
from pydantic import BaseModel, Field
from soothe_sdk.plugin import plugin

from soothe.config.constants import (
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
    DEFAULT_EXECUTE_TIMEOUT,
)
from soothe.foundation.core.security.operation_security import WorkspaceToolOperationSecurity
from soothe.protocols.operation_security import OperationSecurityContext, OperationSecurityRequest
from soothe.toolkits.shell_compat import macos_shell_compatibility_error
from soothe.utils import expand_path

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Match a leading-'/' path token bounded by shell separators. Excludes matches
# that are followed by a quote (likely inside a string literal) and matches
# that are preceded by anything other than the start of the command or a shell
# separator (which would indicate it is part of a larger token like a URL).
_VIRTUAL_PATH_TOKEN_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s;&|<>()=]))"
    r"/(?:[A-Za-z0-9_.\-][A-Za-z0-9_./\-]*)?"
    r"(?=$|[\s;&|<>():])"
)


def _resolve_workspace(workspace_root: str, tool_runtime: Any = None) -> str | None:
    """Resolve effective workspace for shell tools (RFC-103, IG-300)."""
    from soothe.foundation.workspace.runtime_resolution import resolve_workspace_for_tool_execution

    resolved = resolve_workspace_for_tool_execution(
        runtime=tool_runtime,
        fallback=workspace_root or None,
    )
    return str(resolved) if resolved is not None else None


def _resolve_background_log_dir(
    *,
    configured_dir: str | None,
    workspace: str | None,
    tool_runtime: Any = None,
) -> Path:
    """Resolve the directory for ``run_background`` stdout/stderr log files."""
    if configured_dir and str(configured_dir).strip():
        target = expand_path(str(configured_dir).strip())
        target.mkdir(parents=True, exist_ok=True)
        return target

    effective_workspace = _resolve_workspace(workspace or "", tool_runtime)
    if effective_workspace:
        target = expand_path(str(effective_workspace)) / ".soothe" / "background"
        target.mkdir(parents=True, exist_ok=True)
        return target

    from soothe.foundation.workspace import get_virtual_home

    target = get_virtual_home() / "background"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _background_run_error(message: str) -> dict[str, Any]:
    """Standard error payload for ``run_background``."""
    return {"pid": None, "status": "error", "message": message, "log_path": None}


def _format_background_log_header(command: str) -> str:
    """Return a synchronous log preamble written before the shell starts."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"[soothe] background started {ts}\n[soothe] command: {command}\n"


def _background_log_path_for_pid(pid: int, log_dir: Path) -> Path:
    """Standard log file path for a background PID under ``log_dir``."""
    return log_dir / f"bg-{pid}.log"


def _append_background_log_footer(
    pid: int,
    *,
    configured_dir: str | None,
    workspace: str | None,
    tool_runtime: Any = None,
    note: str,
) -> None:
    """Append a footer line to ``bg-{pid}.log`` when the file exists."""
    log_dir = _resolve_background_log_dir(
        configured_dir=configured_dir,
        workspace=workspace,
        tool_runtime=tool_runtime,
    )
    log_path = _background_log_path_for_pid(pid, log_dir)
    if not log_path.is_file():
        return
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[soothe] {note}\n")


def _background_log_dir_from_config(config: Any | None) -> str | None:
    if config is None:
        return None
    try:
        raw = config.tools.execution.background_log_dir
    except AttributeError:
        return None
    return str(raw) if raw else None


def _virtual_mode_from_security(security_config: Any) -> bool:
    """Return True when the workspace is sandboxed (paths outside denied)."""
    if security_config is None:
        return False
    return not bool(getattr(security_config, "allow_paths_outside_workspace", True))


def _translate_virtual_paths_in_command(
    command: str, workspace: str | None, *, virtual_mode: bool
) -> str:
    """Rewrite virtual-workspace `/path` tokens to host-absolute paths.

    Filesystem tools treat a leading '/' as the workspace root; shell commands
    do not. When the LLM borrows a virtual path (e.g. `/CHANGELOG.md`) into a
    shell command, the host shell would walk the real filesystem root instead.
    This translator rewrites only path-shaped tokens whose first segment is not
    a known host root (e.g. /etc, /tmp, /Users), leaving real host paths alone.

    Args:
        command: Raw shell command from the LLM.
        workspace: Effective workspace root (host-absolute path) or None.
        virtual_mode: True when paths-outside-workspace are denied.

    Returns:
        Command string with virtual workspace paths rewritten to host paths.
    """
    if not virtual_mode or not workspace or not command:
        return command

    from soothe.foundation.workspace.tool_path_resolution import should_use_virtual_path_resolution

    workspace_path = Path(workspace).expanduser()
    workspace_str = str(workspace_path).rstrip("/")
    if not workspace_str:
        return command

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if not should_use_virtual_path_resolution(token, workspace_path):
            return token
        suffix = token[1:]  # strip leading '/'
        rewritten = workspace_str if not suffix else f"{workspace_str}/{suffix}"
        logger.debug("Rewrote virtual shell path %r → %r", token, rewritten)
        return rewritten

    return _VIRTUAL_PATH_TOKEN_RE.sub(_replace, command)


class RunCommandInput(BaseModel):
    """Arguments for ``run_command`` (ShellTool-based)."""

    command: str = Field(..., description="The shell command to execute.")
    timeout: int | None = Field(
        default=None,
        description="Optional timeout in seconds (defaults to toolkit timeout).",
    )


def _process_is_alive(pid: int) -> bool:
    """Return whether ``pid`` still exists (signal 0 probe)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Permission denied or similar — treat as alive so callers can escalate.
        return True
    return True


def _kill_process_tree(pid: int, *, sig: int = signal.SIGKILL) -> None:
    """Terminate ``pid`` and its descendants (process group on Unix)."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        with contextlib.suppress(OSError):
            os.kill(pid, sig)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def _run_shell_command_sync(
    command: str,
    *,
    cwd: str | None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command with timeout and process-group teardown on expiry."""
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=sys.platform != "win32",
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            proc.kill()
        _kill_process_tree(proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "",
        stderr="",
    )


class _UnusedShellProcess:
    """``ShellTool`` requires ``process``; Soothe runs commands via ``subprocess``."""

    def run(self, commands: object) -> str:  # pragma: no cover
        raise RuntimeError("RunCommandShellTool does not use BashProcess.run")


class RunCommandShellTool(ShellTool):
    """LangChain :class:`~langchain_community.tools.ShellTool` as ``run_command``.

    Adds operation security, workspace-aware ``cwd``, LangGraph ``ToolRuntime``
    injection, and subprocess execution (IG-336).
    """

    process: Any = Field(default_factory=lambda: _UnusedShellProcess())
    name: str = "run_command"
    description: str = (
        "Execute a shell command and return output. "
        "Use for: CLI tools, system commands, scripts. "
        "Parameters: command (required) - the shell command to run. "
        "Optional: timeout (default: 60 seconds). "
        "Returns: command output (stdout + stderr). "
        "On macOS do not use GNU `timeout`; use the target tool's own timeout flags "
        "(e.g. go test -timeout) or run_background for long jobs. "
        "For long-running commands (>60s), use run_background instead."
    )
    args_schema: type[BaseModel] = RunCommandInput

    workspace_root: str = Field(default="", description="Working directory fallback")
    timeout: int = Field(default=DEFAULT_EXECUTE_TIMEOUT, description="Command timeout in seconds")
    max_output_length: int = Field(default=DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS)
    security_config: Any = Field(default=None, description="Security configuration object")

    def _get_effective_workspace(self, tool_runtime: Any = None) -> str | None:
        """Expose workspace resolution for tests (RFC-103)."""
        return _resolve_workspace(self.workspace_root, tool_runtime)

    def _security_decision(
        self, command: str, tool_name: str, tool_runtime: Any = None
    ) -> tuple[str, str]:
        evaluator = WorkspaceToolOperationSecurity()
        decision = evaluator.evaluate(
            OperationSecurityRequest(
                action_type="tool_call",
                tool_name=tool_name,
                tool_args={"command": command},
                operation_kind="shell_execute",
                command=command,
            ),
            OperationSecurityContext(
                workspace=_resolve_workspace(self.workspace_root, tool_runtime),
                security_config=self.security_config,
            ),
        )
        return decision.verdict, decision.reason

    def _run(
        self,
        command: str,
        timeout: int | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
        run_manager: Any = None,
    ) -> str:
        verdict, reason = self._security_decision(command, self.name, runtime)
        if verdict != "allow":
            logger.warning("Operation security denied command: %s (%s)", command, reason)
            return f"Error: {reason}"

        shell_error = macos_shell_compatibility_error(command)
        if shell_error is not None:
            return shell_error

        actual_timeout = timeout if timeout is not None else self.timeout
        cwd_raw = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(cwd_raw)) if cwd_raw else None

        command = _translate_virtual_paths_in_command(
            command,
            cwd,
            virtual_mode=_virtual_mode_from_security(self.security_config),
        )

        try:
            completed = _run_shell_command_sync(
                command,
                cwd=cwd,
                timeout=actual_timeout,
            )
        except (subprocess.TimeoutExpired, TimeoutError):
            return (
                f"Error: Command timed out after {actual_timeout}s. "
                "The process group was terminated. "
                "For long-running operations, use run_background instead, "
                "or increase the timeout configuration."
            )
        except OSError as e:
            return f"Error executing command: {e}"
        except Exception as e:
            logger.exception("CLI command failed")
            return f"Error executing command: {e}"

        output = completed.stdout or ""
        output = _ANSI_ESCAPE.sub("", output) if output else ""
        if len(output) > self.max_output_length:
            output = output[: self.max_output_length] + "\n... (output truncated)"
        return output.strip()

    async def _arun(
        self,
        command: str,
        timeout: int | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:  # noqa: ASYNC109
        return self._run(command, timeout, runtime=runtime)


class RunPythonInput(BaseModel):
    """Arguments for ``run_python`` (PythonREPLTool-based)."""

    code: str = Field(..., description="Python code to execute.")


def _soothe_python_repl() -> PythonREPL:
    """Isolated REPL globals (not the importing module's ``globals()``)."""
    return PythonREPL.model_construct(_globals={}, _locals=None)


class RunPythonREPLTool(PythonREPLTool):
    """LangChain :class:`~langchain_experimental.tools.python.PythonREPLTool` as ``run_python``.

    Uses ``PythonREPL`` with an isolated namespace; state persists for the lifetime
    of this tool instance (IG-338).
    """

    name: str = "run_python"
    description: str = (
        "Execute Python code in a persistent Python REPL (langchain_experimental). "
        "Variables and imports persist across calls on the same tool instance "
        "(reset when the agent tool catalog is rebuilt). "
        "Parameters: code (required). Use print(...) to display values."
    )
    args_schema: type[BaseModel] = RunPythonInput
    python_repl: PythonREPL = Field(default_factory=_soothe_python_repl)

    def _run(
        self,
        code: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> Any:
        if self.sanitize_input:
            code = sanitize_input(code)
        return self.python_repl.run(code)

    async def _arun(
        self,
        code: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> Any:
        if self.sanitize_input:
            code = sanitize_input(code)
        return await run_in_executor(None, self.python_repl.run, code)


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
        "Returns: process ID, log_path (stdout/stderr log file), and status. "
        "The log header (timestamp + command) is written immediately; use read_file "
        "on log_path to inspect progress. Use kill_process to stop."
    )
    workspace_root: str = Field(default="", description="Working directory for shell")
    background_log_dir: str | None = Field(
        default=None,
        description="Optional override for background log directory",
    )
    security_config: Any = Field(default=None, description="Security configuration object")

    def _security_decision(self, command: str, tool_runtime: Any = None) -> tuple[str, str]:
        evaluator = WorkspaceToolOperationSecurity()
        decision = evaluator.evaluate(
            OperationSecurityRequest(
                action_type="tool_call",
                tool_name=self.name,
                tool_args={"command": command},
                operation_kind="shell_execute",
                command=command,
            ),
            OperationSecurityContext(
                workspace=_resolve_workspace(self.workspace_root, tool_runtime),
                security_config=self.security_config,
            ),
        )
        return decision.verdict, decision.reason

    def _run(
        self,
        command: str,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> dict[str, Any]:
        """Execute command in background process.

        Args:
            command: Command to run in background

        Returns:
            Dict with ``pid``, ``status``, ``message``, and ``log_path``
        """
        verdict, reason = self._security_decision(command, runtime)
        if verdict != "allow":
            return _background_run_error(f"Error: {reason}")

        shell_error = macos_shell_compatibility_error(command)
        if shell_error is not None:
            return _background_run_error(shell_error)

        effective = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(effective)) if effective else None

        command = _translate_virtual_paths_in_command(
            command,
            cwd,
            virtual_mode=_virtual_mode_from_security(self.security_config),
        )

        log_dir = _resolve_background_log_dir(
            configured_dir=self.background_log_dir,
            workspace=cwd,
            tool_runtime=runtime,
        )
        pending_log = log_dir / f"bg-pending-{uuid.uuid4().hex[:12]}.log"
        log_handle = open(pending_log, "w", encoding="utf-8", buffering=1)
        log_handle.write(_format_background_log_header(command))
        log_handle.flush()

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as e:
            log_handle.close()
            with contextlib.suppress(OSError):
                pending_log.unlink(missing_ok=True)
            return _background_run_error(f"Error starting background process: {e}")
        finally:
            log_handle.close()

        log_path = _background_log_path_for_pid(proc.pid, log_dir)
        try:
            pending_log.rename(log_path)
        except OSError:
            logger.debug("Could not rename background log %s → %s", pending_log, log_path)
            log_path = pending_log

        log_path_str = str(log_path)
        return {
            "pid": proc.pid,
            "status": "running",
            "message": (
                f"Background process started with PID: {proc.pid}. "
                f"Log file: {log_path_str} (header written; use read_file to inspect output)."
            ),
            "log_path": log_path_str,
        }

    async def _arun(
        self,
        command: str,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> dict[str, Any]:
        """Async execution (delegates to sync)."""
        return self._run(command, runtime=runtime)


class KillProcessTool(BaseTool):
    """Terminate a background process.

    Use this tool to stop a command that was started with run_background.
    You need the process ID (PID) that was returned when you started the command.
    """

    name: str = "kill_process"
    description: str = (
        "Terminate a background process. "
        "Parameters: pid (required) - process ID from run_background. "
        "Returns: termination status. Appends a footer to bg-{pid}.log when present."
    )
    workspace_root: str = Field(default="", description="Working directory fallback for log lookup")
    background_log_dir: str | None = Field(
        default=None,
        description="Optional override for background log directory",
    )

    def _run(
        self,
        pid: int,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Terminate background process and its children.

        Args:
            pid: Process ID to terminate

        Returns:
            Status message
        """
        if pid <= 0:
            return f"Error: invalid process ID {pid}"

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return f"Process {pid} not found or already terminated"
        except PermissionError:
            return f"Error killing process {pid}: permission denied"
        except OSError as e:
            return f"Error killing process: {e}"

        _kill_process_tree(pid, sig=signal.SIGTERM)
        if _process_is_alive(pid):
            _kill_process_tree(pid, sig=signal.SIGKILL)

        cwd_raw = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(cwd_raw)) if cwd_raw else None
        terminated = not _process_is_alive(pid)
        footer_note = (
            f"process {pid} terminated"
            if terminated
            else f"process {pid} termination signaled (may still be shutting down)"
        )
        _append_background_log_footer(
            pid,
            configured_dir=self.background_log_dir,
            workspace=cwd,
            tool_runtime=runtime,
            note=footer_note,
        )

        if terminated:
            return f"Process {pid} terminated"
        return f"Process {pid} termination signaled (process may still be shutting down)"

    async def _arun(
        self,
        pid: int,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Async execution (delegates to sync)."""
        return self._run(pid, runtime=runtime)


class ExecutionToolkit:
    """Toolkit for shell and Python execution.

    Provides: run_command, run_python, run_background, kill_process
    """

    def __init__(
        self,
        *,
        workspace_root: str = "",
        timeout: int = 60,
        security_config: Any = None,
        max_output_length: int = DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
        background_log_dir: str | None = None,
    ) -> None:
        """Initialize toolkit.

        Args:
            workspace_root: Working directory for commands.
            timeout: Default command timeout in seconds.
            security_config: Security configuration for operation policy.
            max_output_length: Max stdout chars for run_command.
            background_log_dir: Optional override for run_background log directory.
        """
        self._workspace_root = workspace_root
        self._timeout = timeout
        self._security_config = security_config
        self._max_output_length = max_output_length
        self._background_log_dir = background_log_dir

    def get_tools(self) -> list[BaseTool]:
        """Return the four execution tool instances for this toolkit."""
        return [
            RunCommandShellTool(
                workspace_root=self._workspace_root,
                timeout=self._timeout,
                security_config=self._security_config,
                max_output_length=self._max_output_length,
            ),
            RunPythonREPLTool(),
            RunBackgroundTool(
                workspace_root=self._workspace_root,
                security_config=self._security_config,
                background_log_dir=self._background_log_dir,
            ),
            KillProcessTool(
                workspace_root=self._workspace_root,
                background_log_dir=self._background_log_dir,
            ),
        ]


def build_execution_toolkit(
    *,
    config: Any | None = None,
    workspace_root: str = "",
    timeout: int = DEFAULT_EXECUTE_TIMEOUT,
    security_config: Any | None = None,
    max_output_length: int | None = None,
) -> ExecutionToolkit:
    """Construct :class:`ExecutionToolkit` from resolver or plugin config."""
    if security_config is None and config is not None:
        security_config = getattr(config, "security", None)
    return ExecutionToolkit(
        workspace_root=workspace_root,
        timeout=timeout,
        security_config=security_config,
        max_output_length=(
            max_output_length
            if max_output_length is not None
            else _execution_max_output_from_config(config)
        ),
        background_log_dir=_background_log_dir_from_config(config),
    )


def _execution_max_output_from_config(config: Any | None) -> int:
    if config is None:
        return DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS
    try:
        return int(config.agent.loop.tool_output.code_exec_max_output_chars)
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS


@plugin(
    name="execution",
    version="1.0.0",
    description="Shell and Python execution tools",
    trust_level="built-in",
)
class ExecutionPlugin:
    """Execution tools plugin.

    Provides run_command, run_python, run_background, and kill_process tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        workspace_root = getattr(context.config, "workspace_root", "")
        timeout = getattr(context.config, "timeout", 60)

        self._tools = build_execution_toolkit(
            config=context.soothe_config,
            workspace_root=workspace_root,
            timeout=timeout,
        ).get_tools()

        context.logger.info(
            "Loaded %d execution tools (workspace=%s, timeout=%ds)",
            len(self._tools),
            workspace_root,
            timeout,
        )


def _execution_plugin_get_tools(self: ExecutionPlugin) -> list[BaseTool]:
    """Return tools loaded by :meth:`ExecutionPlugin.on_load`.

    Assigned after class creation because ``@plugin`` replaces ``get_tools`` with
    an ``@tool`` method scanner that does not apply to toolkit-backed plugins.
    """
    return self._tools


ExecutionPlugin.get_tools = _execution_plugin_get_tools  # type: ignore[method-assign]
