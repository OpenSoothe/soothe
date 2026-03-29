#!/usr/bin/env python3
"""Check daemon process health.

Verifies:
- PID file exists and contains valid PID
- Process is running
- Unix socket accepts connections
- No stale locks

If daemon is not running, starts a test daemon for validation and cleans up afterward.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from soothe.daemon import pid_path, socket_path

# Track if we started a test daemon
_test_daemon_pid: int | None = None


def check_pid_file() -> dict[str, Any]:
    """Check PID file validity."""
    pf = pid_path()
    if not pf.exists():
        return {
            "name": "pid_file",
            "status": "error",
            "message": f"PID file not found at {pf}",
            "details": {"path": str(pf)},
        }

    try:
        pid_str = pf.read_text().strip()
        pid = int(pid_str)
    except (ValueError, OSError) as e:
        return {
            "name": "pid_file",
            "status": "error",
            "message": f"Invalid PID file: {e}",
            "details": {"path": str(pf)},
        }

    return {
        "name": "pid_file",
        "status": "ok",
        "message": f"PID file exists with PID {pid}",
        "details": {"pid": pid, "path": str(pf)},
    }


def check_process_alive(pid: int) -> dict[str, Any]:
    """Check if process is alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {
            "name": "process_alive",
            "status": "error",
            "message": f"Process {pid} not found (daemon crashed?)",
            "details": {"pid": pid},
        }
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return {
            "name": "process_alive",
            "status": "ok",
            "message": f"Process {pid} running (no signal permission)",
            "details": {"pid": pid},
        }
    except OSError as e:
        return {
            "name": "process_alive",
            "status": "error",
            "message": f"Error checking process: {e}",
            "details": {"pid": pid},
        }

    return {
        "name": "process_alive",
        "status": "ok",
        "message": f"Process {pid} is running",
        "details": {"pid": pid},
    }


def check_socket_connectivity() -> dict[str, Any]:
    """Check Unix socket connectivity."""
    sock = socket_path()
    if not sock.exists():
        return {
            "name": "socket_connectivity",
            "status": "error",
            "message": f"Socket not found at {sock}",
            "details": {"path": str(sock)},
        }

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(sock))
        s.close()
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        return {
            "name": "socket_connectivity",
            "status": "error",
            "message": f"Socket connection failed: {e}",
            "details": {"path": str(sock)},
        }

    return {
        "name": "socket_connectivity",
        "status": "ok",
        "message": f"Socket accepting connections at {sock}",
        "details": {"path": str(sock)},
    }


def check_socket_responsiveness() -> dict[str, Any]:
    """Check if daemon responds with status via socket.

    When a client connects, the daemon immediately sends a status message.
    This test verifies we can connect and receive a valid daemon response.
    """
    sock = socket_path()
    if not sock.exists():
        return {
            "name": "socket_responsiveness",
            "status": "error",
            "message": f"Socket not found at {sock}",
            "details": {"path": str(sock)},
        }

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
            return {
                "name": "socket_responsiveness",
                "status": "error",
                "message": "Daemon connected but sent no response",
                "details": {"path": str(sock)},
            }

        # Parse response
        try:
            response = json.loads(response_line.decode())
        except json.JSONDecodeError as e:
            return {
                "name": "socket_responsiveness",
                "status": "error",
                "message": f"Invalid daemon response: {e}",
                "details": {"path": str(sock), "raw": response_line.decode(errors="replace")},
            }

        # Validate it's a status message
        if response.get("type") != "status":
            return {
                "name": "socket_responsiveness",
                "status": "warning",
                "message": f"Unexpected response type: {response.get('type')}",
                "details": {"path": str(sock), "response": response},
            }

        # Extract daemon state
        state = response.get("state", "unknown")
        thread_id = response.get("thread_id", "")

        return {
            "name": "socket_responsiveness",
            "status": "ok",
            "message": f"Daemon responsive (state={state}, thread={thread_id or 'none'})",
            "details": {
                "path": str(sock),
                "state": state,
                "thread_id": thread_id,
                "response": response,
            },
        }

    except TimeoutError:
        return {
            "name": "socket_responsiveness",
            "status": "error",
            "message": "Daemon socket timeout (no response within 2s)",
            "details": {"path": str(sock)},
        }
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        return {
            "name": "socket_responsiveness",
            "status": "error",
            "message": f"Socket connection failed: {e}",
            "details": {"path": str(sock)},
        }


def check_stale_locks() -> dict[str, Any]:
    """Check for stale lock files."""
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
        return {
            "name": "stale_locks",
            "status": "warning",
            "message": "Stale files detected: " + "; ".join(issues),
            "details": {"issues": issues},
        }

    return {
        "name": "stale_locks",
        "status": "ok",
        "message": "No stale locks detected",
    }


def start_test_daemon() -> dict[str, Any]:
    """Start a test daemon for health check validation.

    Returns:
        Result dict with status and PID if successful.
    """
    global _test_daemon_pid

    # Check if daemon is already running
    sock = socket_path()
    if sock.exists():
        return {
            "name": "test_daemon_start",
            "status": "skipped",
            "message": "Daemon already running (socket exists)",
        }

    # Start daemon in background
    try:
        # Use subprocess to start daemon
        proc = subprocess.Popen(
            [sys.executable, "-m", "soothe.daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        _test_daemon_pid = proc.pid

        # Wait for daemon to initialize (up to 5 seconds)
        max_wait = 5.0
        start_time = time.time()
        while time.time() - start_time < max_wait:
            if sock.exists():
                # Verify socket is responsive
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    s.connect(str(sock))
                    s.close()

                    # Register cleanup handler
                    atexit.register(stop_test_daemon)

                    return {
                        "name": "test_daemon_start",
                        "status": "ok",
                        "message": f"Test daemon started (PID {_test_daemon_pid})",
                        "details": {"pid": _test_daemon_pid},
                    }
                except (ConnectionRefusedError, FileNotFoundError, OSError):
                    pass

            time.sleep(0.1)

        # Daemon didn't start in time
        proc.terminate()
        _test_daemon_pid = None
        return {
            "name": "test_daemon_start",
            "status": "error",
            "message": "Test daemon failed to start within 5 seconds",
        }

    except Exception as e:
        return {
            "name": "test_daemon_start",
            "status": "error",
            "message": f"Failed to start test daemon: {e}",
        }


def stop_test_daemon() -> None:
    """Stop the test daemon if we started one."""
    global _test_daemon_pid

    if _test_daemon_pid is None:
        return

    try:
        # Send SIGTERM to daemon process group
        os.killpg(os.getpgid(_test_daemon_pid), signal.SIGTERM)

        # Wait for process to exit (up to 2 seconds)
        max_wait = 2.0
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                os.kill(_test_daemon_pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break

        # Force kill if still running
        try:
            os.killpg(os.getpgid(_test_daemon_pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    except (ProcessLookupError, PermissionError, OSError):
        # Process already dead
        pass
    finally:
        _test_daemon_pid = None

        # Clean up any leftover files
        pf = pid_path()
        sock = socket_path()
        if pf.exists():
            try:
                pf.unlink()
            except OSError:
                pass
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass


def check_daemon_comprehensive() -> dict[str, Any]:
    """Comprehensive daemon check with socket-first logic.

    This prioritizes socket responsiveness (most reliable indicator) over PID file checks.
    If the daemon responds via socket, it's healthy regardless of PID file state.
    """
    checks = []

    # Priority 1: Socket responsiveness check (most reliable)
    socket_result = check_socket_responsiveness()
    checks.append(socket_result)

    if socket_result["status"] == "ok":
        # Daemon is healthy via socket - run PID checks as informational
        pid_result = check_pid_file()
        checks.append(pid_result)

        # If PID check failed but socket is OK, downgrade to warning
        if pid_result["status"] != "ok":
            pid_result["status"] = "warning"
            pid_result["message"] = f"{pid_result['message']} (daemon healthy via socket)"

        # Check process if PID is valid
        if pid_result.get("details", {}).get("pid"):
            pid = pid_result["details"]["pid"]
            process_result = check_process_alive(pid)
            checks.append(process_result)

            # Downgrade process errors to warnings if socket is OK
            if process_result["status"] != "ok":
                process_result["status"] = "warning"
                process_result["message"] = f"{process_result['message']} (daemon healthy via socket)"
        else:
            checks.append(
                {
                    "name": "process_alive",
                    "status": "warning",
                    "message": "No valid PID to check (daemon healthy via socket)",
                }
            )

        # Check for stale locks
        stale_result = check_stale_locks()
        checks.append(stale_result)

        return {
            "category": "daemon",
            "status": "healthy",
            "checks": checks,
        }

    # Priority 2: No socket response - fall back to PID checks
    pid_result = check_pid_file()
    checks.append(pid_result)

    if pid_result["status"] == "ok" and "pid" in pid_result.get("details", {}):
        pid = pid_result["details"]["pid"]
        process_result = check_process_alive(pid)
        checks.append(process_result)

        if process_result["status"] == "ok":
            # Process alive but socket not responding - degraded state
            stale_result = check_stale_locks()
            checks.append(stale_result)

            return {
                "category": "daemon",
                "status": "warning",
                "checks": checks,
                "message": "Daemon process running but socket not responsive",
            }
        # Stale PID - process dead
        checks.append(
            {
                "name": "stale_locks",
                "status": "error",
                "message": "Stale PID file (process not running)",
            }
        )

        return {
            "category": "daemon",
            "status": "critical",
            "checks": checks,
            "message": "Daemon not running (stale PID file)",
        }
    # No valid PID file
    checks.append(
        {
            "name": "process_alive",
            "status": "skipped",
            "message": "Skipped (no valid PID)",
        }
    )

    # Check for stale locks
    stale_result = check_stale_locks()
    checks.append(stale_result)

    return {
        "category": "daemon",
        "status": "critical",
        "checks": checks,
        "message": "Daemon not running",
    }


def run_checks() -> dict[str, Any]:
    """Run all daemon checks.

    Uses comprehensive socket-first logic to avoid false negatives when PID file is missing.
    If daemon is not running, starts a test daemon for validation and cleans up afterward.
    """
    global _test_daemon_pid

    # Check if daemon is already running
    daemon_was_running = False
    sock = socket_path()
    pf = pid_path()

    if sock.exists() or pf.exists():
        # Daemon might be running, check it
        socket_result = check_socket_responsiveness()
        if socket_result["status"] == "ok":
            daemon_was_running = True

    # If daemon not running, start a test daemon
    test_start_result = None
    if not daemon_was_running:
        test_start_result = start_test_daemon()
        if test_start_result["status"] not in ("ok", "skipped"):
            # Failed to start test daemon
            return {
                "category": "daemon",
                "status": "critical",
                "checks": [
                    test_start_result,
                    {
                        "name": "socket_responsiveness",
                        "status": "error",
                        "message": "No daemon running and test daemon failed to start",
                    },
                    {
                        "name": "pid_file",
                        "status": "error",
                        "message": f"PID file not found at {pf}",
                    },
                    {
                        "name": "process_alive",
                        "status": "skipped",
                        "message": "Skipped (no valid PID)",
                    },
                ],
                "message": "Daemon not running and test daemon failed to start",
            }

    # Run comprehensive daemon check
    result = check_daemon_comprehensive()

    # Add test daemon start info to checks if we started one
    if test_start_result and test_start_result["status"] == "ok":
        result["checks"].insert(0, test_start_result)
        result["daemon_started_by_check"] = True

    return result


def main() -> int:
    """Run checks and output JSON."""
    try:
        result = run_checks()
        print(json.dumps(result, indent=2))

        # Return exit code
        if result["status"] == "healthy":
            return 0
        if result["status"] == "warning":
            return 1
        return 2
    finally:
        # Always cleanup test daemon if we started one
        stop_test_daemon()


if __name__ == "__main__":
    sys.exit(main())
