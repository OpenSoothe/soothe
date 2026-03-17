#!/usr/bin/env python3
"""Check daemon process health.

Verifies:
- PID file exists and contains valid PID
- Process is running
- Unix socket accepts connections
- No stale locks
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from soothe.cli.daemon import pid_path, socket_path
from soothe.config import SOOTHE_HOME


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


def run_checks() -> dict[str, Any]:
    """Run all daemon checks."""
    checks = []

    # Check PID file
    pid_result = check_pid_file()
    checks.append(pid_result)

    # Check process if PID valid
    if pid_result["status"] == "ok" and "pid" in pid_result.get("details", {}):
        pid = pid_result["details"]["pid"]
        process_result = check_process_alive(pid)
        checks.append(process_result)

        # Only check socket if process is alive
        if process_result["status"] == "ok":
            checks.append(check_socket_connectivity())
        else:
            checks.append({
                "name": "socket_connectivity",
                "status": "skipped",
                "message": "Skipped (daemon not running)",
            })
    else:
        checks.append({
            "name": "process_alive",
            "status": "skipped",
            "message": "Skipped (no valid PID)",
        })
        checks.append({
            "name": "socket_connectivity",
            "status": "skipped",
            "message": "Skipped (no valid PID)",
        })

    # Check for stale locks
    checks.append(check_stale_locks())

    # Determine overall status
    status = "healthy"
    for check in checks:
        if check["status"] == "error":
            status = "critical"
            break
        elif check["status"] == "warning" and status != "critical":
            status = "warning"

    return {
        "category": "daemon",
        "status": status,
        "checks": checks,
    }


def main() -> int:
    """Run checks and output JSON."""
    result = run_checks()
    print(json.dumps(result, indent=2))

    # Return exit code
    if result["status"] == "healthy":
        return 0
    elif result["status"] == "warning":
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
