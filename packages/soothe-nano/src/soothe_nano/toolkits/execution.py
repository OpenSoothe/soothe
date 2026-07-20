"""Execution tools (RFC-0016 consolidation).

Consolidates single-purpose execution tools into one module:
- run_command: Synchronous shell (waits for completion; honors per-call timeout)
- run_background: Background shell (PID + log_path; poll via tail_background_log)
- run_python: Python REPL with session persistence
- tail_background_log: Read trailing lines from background logs
- kill_process: Terminate background processes

Follows the pattern from data.py and file_ops.py.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
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

from soothe_nano.config.middleware_access import agent_middleware_config

try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at static analysis time
    ToolRuntime = Any  # type: ignore[misc,assignment]
from pydantic import BaseModel, Field
from soothe_sdk.plugin import plugin
from soothe_sdk.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)

from soothe_nano.config.constants import (
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
    DEFAULT_EXECUTE_TIMEOUT,
    clamp_execute_timeout,
)
from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity
from soothe_nano.toolkits.shell_compat import macos_shell_compatibility_error
from soothe_nano.utils import expand_path

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
    from soothe_nano.workspace.workspace_api import resolve_workspace_for_tool_execution

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

    from soothe_nano.workspace import get_virtual_home

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


def _background_log_retention_from_config(config: Any | None) -> int:
    if config is None:
        return 7
    try:
        return max(0, int(config.tools.execution.background_log_retention_days))
    except (AttributeError, TypeError, ValueError):
        return 7


def _cleanup_stale_background_logs(log_dir: Path, retention_days: int) -> None:
    """Remove ``bg-*.log`` files older than ``retention_days`` (no-op when 0)."""
    if retention_days <= 0:
        return
    cutoff = time.time() - (retention_days * 86400)
    for path in log_dir.glob("bg-*.log"):
        with contextlib.suppress(OSError):
            if path.stat().st_mtime < cutoff:
                path.unlink()


def _tail_text_file(path: Path, *, max_lines: int) -> str:
    """Return up to the last ``max_lines`` lines from a text file."""
    if not path.is_file():
        return f"Error: log file not found: {path}"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading log file: {exc}"
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content if content.endswith("\n") or not content else content + "\n"
    tail = "\n".join(lines[-max_lines:])
    return f"{tail}\n"


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

    from soothe_nano.workspace.workspace_paths import should_use_virtual_path_resolution

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
        description=(
            "Optional timeout in seconds (defaults to toolkit timeout, max 5h). "
            "Pass for bounded jobs longer than 60s; use run_background for daemons."
        ),
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


_PRODUCTION_DAEMON_WS_PORT = 8765


def _soothed_pid_from_pidfile() -> int | None:
    """Return the host daemon PID from ``SOOTHE_HOME/soothed.pid`` when present."""
    try:
        from soothe_nano.config import SOOTHE_HOME

        pf = Path(SOOTHE_HOME).expanduser() / "soothed.pid"
        if not pf.is_file():
            return None
        return int(pf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, TypeError, ImportError):
        return None


def _pid_listening_on_port(port: int) -> int | None:
    """Best-effort PID of the process listening on ``port`` (macOS/Linux ``lsof``)."""
    if port <= 0:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in (completed.stdout or "").splitlines():
        token = line.strip()
        if token.isdigit():
            return int(token)
    return None


def _protected_kill_refusal(pid: int) -> str | None:
    """Return an error message when ``pid`` must not be killed by agent tools.

    Protects the in-process daemon (thread-pool mode), the host ``soothed``
    PID file target, and whoever is listening on the production WebSocket port.
    """
    if pid == os.getpid():
        return (
            f"Error: refusing to kill PID {pid} — that is the current agent/daemon process. "
            "kill_process is only for PIDs returned by run_background."
        )
    with contextlib.suppress(OSError):
        if pid == os.getppid():
            return (
                f"Error: refusing to kill parent PID {pid}. "
                "kill_process is only for PIDs returned by run_background."
            )

    daemon_pid = _soothed_pid_from_pidfile()
    if daemon_pid is not None and pid == daemon_pid:
        return (
            f"Error: refusing to kill Soothe daemon PID {pid} (soothed.pid). "
            "Stop the host daemon from an outside shell with `soothed stop`, "
            "not via agent tools."
        )

    listener = _pid_listening_on_port(_PRODUCTION_DAEMON_WS_PORT)
    if listener is not None and pid == listener:
        return (
            f"Error: refusing to kill PID {pid} listening on "
            f"ws://127.0.0.1:{_PRODUCTION_DAEMON_WS_PORT} (live Soothe daemon). "
            "kill_process is only for PIDs returned by run_background."
        )
    return None


def _kill_process_tree(pid: int, *, sig: int = signal.SIGKILL) -> None:
    """Terminate ``pid`` and its descendants (process group on Unix).

    Never ``killpg`` the caller's own process group — that would take down the
    in-process daemon when a child somehow shares the agent PGID.
    """
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
    try:
        self_pgid = os.getpgid(0)
    except OSError:
        self_pgid = None
    if self_pgid is not None and pgid == self_pgid:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, sig)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def _terminate_shell_process(proc: subprocess.Popen[str]) -> None:
    """Kill ``proc`` and its process group, then drain pipes."""
    with contextlib.suppress(OSError):
        proc.kill()
    _kill_process_tree(proc.pid)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)


def _collect_capped_stdout(
    proc: subprocess.Popen[str],
    *,
    command: str,
    timeout: int,
    max_output_chars: int,
) -> subprocess.CompletedProcess[str]:
    """Read stdout with an output cap while honoring ``timeout`` for silent processes.

    A blocking ``stdout.read()`` in the main thread can stall past the deadline when
    the child produces no output (common for long-running servers). A daemon reader
    thread performs blocking reads; the main loop enforces the deadline via timed
    queue reads.
    """
    chunk_queue: queue.Queue[str | None] = queue.Queue()
    reader_errors: list[BaseException] = []

    def _reader() -> None:
        try:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(4096)
                if chunk == "":
                    break
                chunk_queue.put(chunk)
        except BaseException as exc:
            reader_errors.append(exc)
        finally:
            chunk_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True, name="run_command-stdout")
    reader.start()

    stdout_parts: list[str] = []
    total = 0
    truncated = False
    deadline = time.monotonic() + timeout

    while True:
        if reader_errors:
            raise reader_errors[0]

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_shell_process(proc)
            reader.join(timeout=1)
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

        try:
            chunk = chunk_queue.get(timeout=min(remaining, 0.05))
        except queue.Empty:
            if proc.poll() is not None and chunk_queue.empty():
                break
            continue

        if chunk is None:
            break

        if total + len(chunk) > max_output_chars:
            stdout_parts.append(chunk[: max_output_chars - total])
            truncated = True
            _terminate_shell_process(proc)
            reader.join(timeout=1)
            break

        stdout_parts.append(chunk)
        total += len(chunk)

    if not truncated:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _terminate_shell_process(proc)
            reader.join(timeout=1)
            raise
        reader.join(timeout=1)

    stdout = "".join(stdout_parts)
    if truncated:
        stdout = stdout + "\n... (output truncated)"
    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr="",
    )


def _run_shell_command_sync(
    command: str,
    *,
    cwd: str | None,
    timeout: int,
    max_output_chars: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command with timeout and optional streaming stdout cap."""
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=sys.platform != "win32",
    )
    if max_output_chars is None or proc.stdout is None:
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_shell_process(proc)
            raise
        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout or "",
            stderr="",
        )

    return _collect_capped_stdout(
        proc,
        command=command,
        timeout=timeout,
        max_output_chars=max_output_chars,
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
        "Run a shell command synchronously and return stdout+stderr when it finishes. "
        "Use for: quick CLI checks, short scripts, bounded builds/tests you can wait for. "
        "Parameters: command (required); optional timeout in seconds (default 60). "
        "Pass timeout for longer sync work (e.g. timeout=3600 for a 1h build; max 5h). "
        "Do NOT use for servers/daemons, foreground services, or jobs with no end — "
        "use run_background instead. "
        "On macOS do not use GNU `timeout`; use native tool flags (e.g. go test -timeout) "
        "or run_background for open-ended jobs."
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

        actual_timeout = clamp_execute_timeout(timeout if timeout is not None else self.timeout)
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
                max_output_chars=self.max_output_length,
            )
        except (subprocess.TimeoutExpired, TimeoutError):
            return (
                f"Error: Command timed out after {actual_timeout}s. "
                "The process group was terminated. "
                "For servers/daemons or open-ended jobs, use run_background; "
                "for bounded sync work, pass a higher timeout argument."
            )
        except OSError as e:
            return f"Error executing command: {e}"
        except Exception as e:
            logger.exception("CLI command failed")
            return f"Error executing command: {e}"

        output = completed.stdout or ""
        output = _ANSI_ESCAPE.sub("", output) if output else ""
        return output.strip()

    async def _arun(
        self,
        command: str,
        timeout: int | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        return await run_in_executor(
            None,
            functools.partial(self._run, command, timeout, runtime=runtime),
        )


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
    """Background shell execution via ``run_background`` (see tool description)."""

    name: str = "run_background"
    description: str = (
        "Start a shell command in the background without waiting for completion. "
        "Use for: servers/daemons, training jobs, installs/builds you will poll later, "
        "or any process that may run indefinitely. "
        "Returns immediately with PID and log_path (stdout/stderr appended to the log). "
        "Poll output via tail_background_log or read_file on log_path; stop via kill_process. "
        "Do NOT use when you need exit code/output in the same turn — use run_command "
        "with an explicit timeout instead. "
        "Parameters: command (required)."
    )
    workspace_root: str = Field(default="", description="Working directory for shell")
    background_log_dir: str | None = Field(
        default=None,
        description="Optional override for background log directory",
    )
    background_log_retention_days: int = Field(
        default=7,
        ge=0,
        description="Delete bg-*.log files older than this many days on spawn (0=off)",
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
        _cleanup_stale_background_logs(log_dir, self.background_log_retention_days)
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


class TailBackgroundLogInput(BaseModel):
    """Arguments for ``tail_background_log``."""

    pid: int = Field(..., description="Process ID from run_background.")
    lines: int = Field(
        default=50,
        ge=1,
        le=5000,
        description="Number of trailing lines to return (default 50).",
    )


class TailBackgroundLogTool(BaseTool):
    """Read the trailing lines of a ``run_background`` log file."""

    name: str = "tail_background_log"
    description: str = (
        "Read the last N lines from a run_background log file (bg-{pid}.log). "
        "Parameters: pid (required), lines (optional, default 50). "
        "Use instead of read_file for large or growing background logs."
    )
    args_schema: type[BaseModel] = TailBackgroundLogInput
    workspace_root: str = Field(default="", description="Working directory fallback")
    background_log_dir: str | None = Field(
        default=None,
        description="Optional override for background log directory",
    )

    def _run(
        self,
        pid: int,
        lines: int = 50,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        if pid <= 0:
            return f"Error: invalid process ID {pid}"

        cwd_raw = _resolve_workspace(self.workspace_root, runtime)
        cwd = str(expand_path(cwd_raw)) if cwd_raw else None
        log_dir = _resolve_background_log_dir(
            configured_dir=self.background_log_dir,
            workspace=cwd,
            tool_runtime=runtime,
        )
        log_path = _background_log_path_for_pid(pid, log_dir)
        return _tail_text_file(log_path, max_lines=lines)

    async def _arun(
        self,
        pid: int,
        lines: int = 50,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        return self._run(pid, lines, runtime=runtime)


class KillProcessTool(BaseTool):
    """Terminate a background process.

    Use this tool to stop a command that was started with run_background.
    You need the process ID (PID) that was returned when you started the command.
    """

    name: str = "kill_process"
    description: str = (
        "Terminate a background process started with run_background. "
        "Parameters: pid (required) — only use the PID returned by run_background. "
        "Do not kill the agent host process or use pkill/killall against the runtime "
        "that spawned you. "
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

        refusal = _protected_kill_refusal(pid)
        if refusal is not None:
            return refusal

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

    Provides: run_command, run_python, run_background, tail_background_log, kill_process
    """

    def __init__(
        self,
        *,
        workspace_root: str = "",
        timeout: int = 60,
        security_config: Any = None,
        max_output_length: int = DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
        background_log_dir: str | None = None,
        background_log_retention_days: int = 7,
    ) -> None:
        """Initialize toolkit.

        Args:
            workspace_root: Working directory for commands.
            timeout: Default command timeout in seconds.
            security_config: Security configuration for operation policy.
            max_output_length: Max stdout chars for run_command.
            background_log_dir: Optional override for run_background log directory.
            background_log_retention_days: Prune bg-*.log older than this (0=off).
        """
        self._workspace_root = workspace_root
        self._timeout = timeout
        self._security_config = security_config
        self._max_output_length = max_output_length
        self._background_log_dir = background_log_dir
        self._background_log_retention_days = background_log_retention_days

    def get_tools(self) -> list[BaseTool]:
        """Return the five execution tool instances for this toolkit."""
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
                background_log_retention_days=self._background_log_retention_days,
            ),
            TailBackgroundLogTool(
                workspace_root=self._workspace_root,
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
        background_log_retention_days=_background_log_retention_from_config(config),
    )


def _execution_max_output_from_config(config: Any | None) -> int:
    if config is None:
        return DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS
    try:
        return int(agent_middleware_config(config).tool_output.code_exec_max_output_chars)
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

    Provides run_command, run_python, run_background, tail_background_log, and kill_process tools.
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
