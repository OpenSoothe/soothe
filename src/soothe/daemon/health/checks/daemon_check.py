"""Daemon health check implementation."""

import json
import os
import socket

from soothe.config import SootheConfig
from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_pid_file() -> CheckResult:
    """Check PID file validity."""
    from soothe.daemon.paths import pid_path

    pf = pid_path()
    if not pf.exists():
        return CheckResult(
            name="pid_file",
            status=CheckStatus.INFO,
            message=f"PID file not found at {pf} (daemon not running)",
            details={"path": str(pf)},
        )

    try:
        pid_str = pf.read_text().strip()
        pid = int(pid_str)
    except (ValueError, OSError) as e:
        return CheckResult(
            name="pid_file",
            status=CheckStatus.WARNING,
            message=f"Invalid PID file: {e}",
            details={"path": str(pf)},
        )

    return CheckResult(
        name="pid_file",
        status=CheckStatus.OK,
        message=f"PID file exists with PID {pid}",
        details={"pid": pid, "path": str(pf)},
    )


def _check_process_alive(pid: int) -> CheckResult:
    """Check if process is alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return CheckResult(
            name="process_alive",
            status=CheckStatus.ERROR,
            message=f"Process {pid} not found (daemon crashed?)",
            details={"pid": pid},
        )
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return CheckResult(
            name="process_alive",
            status=CheckStatus.OK,
            message=f"Process {pid} running (no signal permission)",
            details={"pid": pid},
        )
    except OSError as e:
        return CheckResult(
            name="process_alive",
            status=CheckStatus.ERROR,
            message=f"Error checking process: {e}",
            details={"pid": pid},
        )

    return CheckResult(
        name="process_alive",
        status=CheckStatus.OK,
        message=f"Process {pid} is running",
        details={"pid": pid},
    )


def _check_socket_connectivity() -> CheckResult:
    """Check Unix socket connectivity."""
    from soothe.daemon.paths import socket_path

    sock = socket_path()
    if not sock.exists():
        return CheckResult(
            name="socket_connectivity",
            status=CheckStatus.INFO,
            message=f"Socket not found at {sock} (daemon not running)",
            details={"path": str(sock)},
        )

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(sock))
        s.close()
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        return CheckResult(
            name="socket_connectivity",
            status=CheckStatus.WARNING,
            message=f"Socket connection failed: {e}",
            details={"path": str(sock)},
        )

    return CheckResult(
        name="socket_connectivity",
        status=CheckStatus.OK,
        message=f"Socket accepting connections at {sock}",
        details={"path": str(sock)},
    )


def _check_socket_responsiveness() -> CheckResult:
    """Check if daemon responds with status via socket.

    When a client connects, the daemon immediately sends a status message.
    This test verifies we can connect and receive a valid daemon response.
    """
    from soothe.daemon.paths import socket_path

    sock = socket_path()
    if not sock.exists():
        return CheckResult(
            name="socket_responsiveness",
            status=CheckStatus.INFO,
            message=f"Socket not found at {sock} (daemon not running)",
            details={"path": str(sock)},
        )

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(sock))

        # Read initial status message that daemon sends on connect
        # Daemon protocol: JSON messages separated by newlines
        response_line = b""
        while True:
            chunk = s.recv(1)
            if not chunk or chunk == b"\n":
                break
            response_line += chunk

        s.close()

        if not response_line:
            return CheckResult(
                name="socket_responsiveness",
                status=CheckStatus.WARNING,
                message="Daemon connected but sent no response",
                details={"path": str(sock)},
            )

        # Parse response
        try:
            response = json.loads(response_line.decode())
        except json.JSONDecodeError as e:
            return CheckResult(
                name="socket_responsiveness",
                status=CheckStatus.WARNING,
                message=f"Invalid daemon response: {e}",
                details={"path": str(sock), "raw": response_line.decode(errors="replace")},
            )

        # Validate it's a status message
        if response.get("type") != "status":
            return CheckResult(
                name="socket_responsiveness",
                status=CheckStatus.WARNING,
                message=f"Unexpected response type: {response.get('type')}",
                details={"path": str(sock), "response": response},
            )

        # Extract daemon state
        state = response.get("state", "unknown")
        thread_id = response.get("thread_id", "")

        return CheckResult(
            name="socket_responsiveness",
            status=CheckStatus.OK,
            message=f"Daemon responsive (state={state}, thread={thread_id or 'none'})",
            details={
                "path": str(sock),
                "state": state,
                "thread_id": thread_id,
                "response": response,
            },
        )

    except TimeoutError:
        return CheckResult(
            name="socket_responsiveness",
            status=CheckStatus.WARNING,
            message="Daemon socket timeout (no response within 2s)",
            details={"path": str(sock)},
        )
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        return CheckResult(
            name="socket_responsiveness",
            status=CheckStatus.WARNING,
            message=f"Socket connection failed: {e}",
            details={"path": str(sock)},
        )


def _check_stale_locks() -> CheckResult:
    """Check for stale lock files."""
    from soothe.daemon.paths import pid_path, socket_path

    pf = pid_path()
    issues = []

    if pf.exists():
        try:
            pid_str = pf.read_text().strip()
            pid = int(pid_str)
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, OSError):
            issues.append(f"Stale PID file at {pf}")

    sock = socket_path()
    if sock.exists():
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(str(sock))
            s.close()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            issues.append(f"Stale socket at {sock}")

    if issues:
        return CheckResult(
            name="stale_locks",
            status=CheckStatus.WARNING,
            message="Stale files detected: " + "; ".join(issues),
            details={"issues": issues},
        )

    return CheckResult(
        name="stale_locks",
        status=CheckStatus.OK,
        message="No stale locks detected",
    )


async def check_daemon(config: SootheConfig | None = None) -> CategoryResult:  # noqa: ARG001
    """Check daemon health.

    Uses socket-first logic to prioritize actual daemon responsiveness
    over PID file checks.

    Args:
        config: SootheConfig instance (not used for daemon checks)

    Returns:
        CategoryResult with daemon check results
    """
    checks = []

    # Priority 1: Socket responsiveness check (most reliable)
    socket_result = _check_socket_responsiveness()
    checks.append(socket_result)

    if socket_result.status == CheckStatus.OK:
        # Daemon is healthy via socket - run PID checks as informational
        pid_result = _check_pid_file()
        checks.append(pid_result)

        # If PID check failed but socket is OK, downgrade to warning
        if pid_result.status != CheckStatus.OK and pid_result.details.get("pid"):
            pid_result.status = CheckStatus.WARNING
            pid_result.message = f"{pid_result.message} (daemon healthy via socket)"

        # Check process if PID is valid
        if pid_result.details.get("pid"):
            pid = pid_result.details["pid"]
            process_result = _check_process_alive(pid)
            checks.append(process_result)

            # Downgrade process errors to warnings if socket is OK
            if process_result.status != CheckStatus.OK:
                process_result.status = CheckStatus.WARNING
                process_result.message = f"{process_result.message} (daemon healthy via socket)"
        else:
            checks.append(
                CheckResult(
                    name="process_alive",
                    status=CheckStatus.WARNING,
                    message="No valid PID to check (daemon healthy via socket)",
                )
            )

        # Check for stale locks
        stale_result = _check_stale_locks()
        checks.append(stale_result)

    else:
        # No socket response - fall back to PID checks
        pid_result = _check_pid_file()
        checks.append(pid_result)

        if pid_result.status == CheckStatus.OK and pid_result.details.get("pid"):
            pid = pid_result.details["pid"]
            process_result = _check_process_alive(pid)
            checks.append(process_result)

            if process_result.status == CheckStatus.OK:
                # Process alive but socket not responding - degraded state
                stale_result = _check_stale_locks()
                checks.append(stale_result)

                return CategoryResult(
                    category="daemon",
                    status=CheckStatus.WARNING,
                    checks=checks,
                    message="Daemon process running but socket not responsive",
                )
            # Stale PID - process dead
            checks.append(
                CheckResult(
                    name="stale_locks",
                    status=CheckStatus.WARNING,
                    message="Stale PID file (process not running)",
                )
            )

            return CategoryResult(
                category="daemon",
                status=CheckStatus.WARNING,
                checks=checks,
                message="Daemon not running (stale PID file)",
            )
        # No valid PID file
        checks.append(
            CheckResult(
                name="process_alive",
                status=CheckStatus.SKIPPED,
                message="Skipped (no valid PID)",
            )
        )

        # Check for stale locks
        stale_result = _check_stale_locks()
        checks.append(stale_result)

        return CategoryResult(
            category="daemon",
            status=CheckStatus.INFO,
            checks=checks,
            message="Daemon not running (optional for CLI usage)",
        )

    # Calculate overall status
    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="daemon",
        status=overall_status,
        checks=checks,
    )
