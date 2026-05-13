"""Execution tools (RFC-0016 consolidation).

Consolidates single-purpose execution tools into one module:
- run_command: Execute shell commands synchronously (langchain_community ShellTool)
- run_python: Execute Python code (langchain_experimental PythonREPLTool)
- run_background: Run commands in background
- kill_process: Terminate background processes

Follows the pattern from image.py and audio.py.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
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

from soothe.config.constants import DEFAULT_EXECUTE_TIMEOUT
from soothe.core.governance.operation_security import WorkspaceToolOperationSecurity
from soothe.protocols.operation_security import OperationSecurityContext, OperationSecurityRequest
from soothe.utils import expand_path

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _workspace_from_tool_runtime(tool_runtime: Any) -> str | None:
    """Resolve workspace from injected ``ToolRuntime`` (config + graph state).

    ``ToolNode`` supplies ``runtime.config`` and ``runtime.state``. For sync tools
    executed on a worker thread, ``langgraph.config.get_config()`` may be empty while
    ``configurable["workspace"]`` is still missing from the per-call copy. Prefer
    ``state["workspace"]`` for subgraphs (e.g. explore), else the latest human message
    ``workspace`` in ``state["messages"]`` (RFC-103, IG-300).

    Args:
        tool_runtime: LangGraph ``ToolRuntime`` (or compatible duck-typed object).

    Returns:
        Absolute or raw workspace string, or ``None`` if not found.
    """
    if tool_runtime is None:
        return None
    cfg = getattr(tool_runtime, "config", None)
    if isinstance(cfg, dict):
        configurable = cfg.get("configurable")
        if isinstance(configurable, dict):
            workspace = configurable.get("workspace")
            if isinstance(workspace, str) and workspace.strip():
                return workspace.strip()

    state = getattr(tool_runtime, "state", None)
    if not isinstance(state, dict):
        return None
    # Subgraphs (e.g. explore) set ``state["workspace"]`` without LoopHumanMessage rows.
    direct_ws = state.get("workspace")
    if isinstance(direct_ws, str) and direct_ws.strip():
        return direct_ws.strip()
    messages = state.get("messages")
    if not isinstance(messages, (list, tuple)):
        return None
    for msg in reversed(messages):
        ws = getattr(msg, "workspace", None)
        if isinstance(ws, str) and ws.strip():
            return ws.strip()
        if isinstance(msg, dict):
            ak = msg.get("additional_kwargs")
            if isinstance(ak, dict):
                cand = ak.get("workspace")
                if isinstance(cand, str) and cand.strip():
                    return cand.strip()
            top = msg.get("workspace")
            if isinstance(top, str) and top.strip():
                return top.strip()
    return None


def _resolve_workspace(workspace_root: str, tool_runtime: Any = None) -> str | None:
    """Resolve effective workspace for shell tools (RFC-103, IG-300).

    Priority:
        1. ``ToolRuntime.config["configurable"]["workspace"]`` when set
        2. ``ToolRuntime.state["workspace"]`` (e.g. explore subgraph thread workspace)
        3. Latest ``LoopHumanMessage`` / message ``workspace`` in ``state["messages"]``
        4. LangGraph ``get_config()`` configurable
        5. ContextVar / ``workspace_root`` static fallback

    Args:
        workspace_root: Daemon-configured default workspace.
        tool_runtime: Optional injected LangGraph tool runtime.

    Returns:
        Effective workspace path or ``None``.
    """
    from_runtime = _workspace_from_tool_runtime(tool_runtime)
    if from_runtime:
        return str(from_runtime)

    try:
        from langgraph.config import get_config

        config = get_config()
        configurable = config.get("configurable", {})
        workspace = configurable.get("workspace")
        if workspace:
            return str(workspace)
    except Exception:  # noqa: S110
        pass

    from soothe.core import FrameworkFilesystem

    dynamic_workspace = FrameworkFilesystem.get_current_workspace()
    if dynamic_workspace:
        return str(dynamic_workspace)

    return workspace_root or None


class RunCommandInput(BaseModel):
    """Arguments for ``run_command`` (ShellTool-based)."""

    command: str = Field(..., description="The shell command to execute.")
    timeout: int | None = Field(
        default=None,
        description="Optional timeout in seconds (defaults to toolkit timeout).",
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
        "For long-running commands (>60s), use run_background instead."
    )
    args_schema: type[BaseModel] = RunCommandInput

    workspace_root: str = Field(default="", description="Working directory fallback")
    timeout: int = Field(default=DEFAULT_EXECUTE_TIMEOUT, description="Command timeout in seconds")
    max_output_length: int = Field(default=10000)
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

        actual_timeout = timeout if timeout is not None else self.timeout
        cwd_raw = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(cwd_raw)) if cwd_raw else None

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=actual_timeout,
            )
        except subprocess.TimeoutExpired:
            return (
                f"Error: Command timed out after {actual_timeout}s. "
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


def cleanup_execution_resources() -> None:
    """Compatibility hook for teardown tests (persistent shell removed in IG-336)."""


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
        "Variables and imports persist across calls for this tool instance. "
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
        "Returns: process ID for tracking. "
        "Use kill_process to stop background commands."
    )
    workspace_root: str = Field(default="", description="Working directory for shell")
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
            Dict with 'pid', 'status', and 'message'
        """
        verdict, reason = self._security_decision(command, runtime)
        if verdict != "allow":
            return {"pid": None, "status": "error", "message": f"Error: {reason}"}

        effective = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(effective)) if effective else None

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return {
                "pid": None,
                "status": "error",
                "message": f"Error starting background process: {e}",
            }
        return {
            "pid": proc.pid,
            "status": "running",
            "message": f"Background process started with PID: {proc.pid}",
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
        "Returns: termination status."
    )

    def _run(self, pid: int) -> str:
        """Terminate background process.

        Args:
            pid: Process ID to terminate

        Returns:
            Status message
        """
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return f"Process {pid} not found or already terminated"
        except PermissionError:
            return f"Error killing process {pid}: permission denied"
        except OSError as e:
            return f"Error killing process: {e}"
        else:
            return f"Process {pid} terminated"

    async def _arun(self, pid: int) -> str:
        """Async execution (delegates to sync)."""
        return self._run(pid)


class ExecutionToolkit:
    """Toolkit for shell and Python execution.

    Provides: run_command, run_python, run_background, kill_process
    """

    def __init__(
        self, *, workspace_root: str = "", timeout: int = 60, security_config: Any = None
    ) -> None:
        """Initialize toolkit.

        Args:
            workspace_root: Working directory for commands.
            timeout: Default command timeout in seconds.
        """
        self._workspace_root = workspace_root
        self._timeout = timeout
        self._security_config = security_config

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Args:
            workspace_root: Working directory for shell sessions.
            timeout: Default timeout for shell commands.

        Returns:
            List of execution BaseTool instances.
        """
        return [
            RunCommandShellTool(
                workspace_root=self._workspace_root,
                timeout=self._timeout,
                security_config=self._security_config,
            ),
            RunPythonREPLTool(),
            RunBackgroundTool(
                workspace_root=self._workspace_root,
                security_config=self._security_config,
            ),
            KillProcessTool(),
        ]


def create_execution_tools(
    *, workspace_root: str = "", timeout: int = 60, security_config: Any = None
) -> list[BaseTool]:
    """Factory function to create execution tools.

    Args:
        workspace_root: Working directory for commands.
        timeout: Default command timeout in seconds.

    Returns:
        List of execution BaseTool instances.
    """
    toolkit = ExecutionToolkit(
        workspace_root=workspace_root,
        timeout=timeout,
        security_config=security_config,
    )
    return toolkit.get_tools()


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
        security_config = getattr(context.soothe_config, "security", None)

        toolkit = ExecutionToolkit(
            workspace_root=workspace_root,
            timeout=timeout,
            security_config=security_config,
        )
        self._tools = toolkit.get_tools()

        context.logger.info(
            "Loaded %d execution tools (workspace=%s, timeout=%ds)",
            len(self._tools),
            workspace_root,
            timeout,
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of execution tool instances.
        """
        return self._tools
