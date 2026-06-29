"""Daemon health check implementation."""

import os

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_pid_file() -> CheckResult:
    """Check PID file validity."""
    from soothe_daemon.bootstrap.paths import pid_path

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


def _check_websocket_connectivity(config: SootheDaemonConfig | None) -> CheckResult:
    """Check WebSocket transport connectivity (RFC-450)."""
    from soothe_daemon.server import SootheDaemon

    ws_host = config.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.transports.websocket.port if config else 8765

    # Use existing port check method from server.py
    if SootheDaemon._is_port_live(ws_host, ws_port):
        return CheckResult(
            name="websocket_connectivity",
            status=CheckStatus.OK,
            message=f"WebSocket accepting connections at {ws_host}:{ws_port}",
            details={"host": ws_host, "port": ws_port},
        )

    return CheckResult(
        name="websocket_connectivity",
        status=CheckStatus.INFO,
        message="WebSocket not accepting connections (daemon not running)",
        details={"host": ws_host, "port": ws_port},
    )


def _check_daemon_readiness(config: SootheDaemonConfig | None) -> CheckResult:
    """Check daemon readiness state via WebSocket handshake (RFC-450)."""
    import asyncio
    import json

    ws_host = config.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.transports.websocket.port if config else 8765
    ws_url = f"ws://{ws_host}:{ws_port}"

    try:

        async def handshake() -> dict | None:
            """Perform WebSocket handshake and receive connection_ack message."""
            import websockets

            async with websockets.connect(ws_url, timeout=2.0) as ws:
                # Send connection_init (RFC-450 §8.2)
                init_msg = {
                    "proto": "1",
                    "type": "connection_init",
                    "params": {
                        "client_version": "health-check",
                        "accept_proto": ["1"],
                        "capabilities": ["streaming", "heartbeat"],
                    },
                }
                await ws.send(json.dumps(init_msg))
                # Wait for connection_ack
                message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(message)
                if data.get("type") == "connection_ack":
                    return data.get("result") or {}
            return None

        ack_result = asyncio.run(handshake())
        if ack_result:
            state = ack_result.get("readiness_state", "unknown")
            status_map = {
                "ready": CheckStatus.OK,
                "degraded": CheckStatus.WARNING,
                "error": CheckStatus.ERROR,
                "starting": CheckStatus.INFO,
                "warming": CheckStatus.INFO,
                "stopped": CheckStatus.INFO,
                "incompatible": CheckStatus.ERROR,
            }

            return CheckResult(
                name="daemon_readiness",
                status=status_map.get(state, CheckStatus.WARNING),
                message=f"Daemon readiness state: {state}",
                details={
                    "state": state,
                    "protocol_version": ack_result.get("protocol_version"),
                    "server_version": ack_result.get("server_version"),
                },
            )

        return CheckResult(
            name="daemon_readiness",
            status=CheckStatus.WARNING,
            message="No connection_ack received",
        )

    except Exception as e:
        return CheckResult(
            name="daemon_readiness",
            status=CheckStatus.INFO,
            message=f"Readiness check failed (daemon not running): {e}",
        )


def _check_daemon_uptime(pid: int | None) -> CheckResult:
    """Calculate daemon uptime from PID start time."""
    if not pid:
        return CheckResult(
            name="daemon_uptime",
            status=CheckStatus.SKIPPED,
            message="No PID to check uptime",
        )

    try:
        import time
        from datetime import UTC, datetime

        import psutil

        process = psutil.Process(pid)
        start_time = process.create_time()
        uptime_seconds = time.time() - start_time

        # Format uptime human-readable
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        return CheckResult(
            name="daemon_uptime",
            status=CheckStatus.INFO,
            message=f"Daemon uptime: {hours}h {minutes}m",
            details={
                "pid": pid,
                "start_time": datetime.fromtimestamp(start_time, UTC).isoformat(),
                "uptime_seconds": uptime_seconds,
            },
        )
    except Exception as e:
        return CheckResult(
            name="daemon_uptime",
            status=CheckStatus.WARNING,
            message=f"Uptime check failed: {e}",
        )


def _check_stale_locks(config: SootheDaemonConfig | None) -> CheckResult:
    """Check for stale PID files and zombie daemon."""
    from soothe_daemon.bootstrap.paths import pid_path
    from soothe_daemon.server import SootheDaemon

    pf = pid_path()
    issues = []

    # Check stale PID file
    if pf.exists():
        try:
            pid_str = pf.read_text().strip()
            pid = int(pid_str)
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, OSError):
            issues.append(f"Stale PID file at {pf}")

    # Check zombie daemon (PID valid but WebSocket dead)
    if pf.exists():
        try:
            pid_str = pf.read_text().strip()
            pid = int(pid_str)
            os.kill(pid, 0)  # PID valid

            # Check if WebSocket port is live
            ws_host = config.transports.websocket.host if config else "127.0.0.1"
            ws_port = config.transports.websocket.port if config else 8765
            if not SootheDaemon._is_port_live(ws_host, ws_port):
                issues.append(f"Zombie daemon (PID {pid} alive but WebSocket port {ws_port} dead)")
        except (ValueError, ProcessLookupError, OSError):
            pass  # Already caught above

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


async def check_daemon(config: SootheDaemonConfig | None = None) -> CategoryResult:
    """Check daemon health with WebSocket-first priority (RFC-450).

    Uses WebSocket-first logic to prioritize actual daemon responsiveness
    over PID file checks.

    Args:
        config: ``SootheDaemonConfig`` instance for transport configuration

    Returns:
        CategoryResult with daemon check results
    """
    checks = []

    # Priority 1: WebSocket connectivity (primary transport)
    ws_result = _check_websocket_connectivity(config)
    checks.append(ws_result)

    if ws_result.status == CheckStatus.OK:
        # WebSocket healthy - run informational checks

        # Readiness state check (WebSocket handshake)
        readiness_result = _check_daemon_readiness(config)
        checks.append(readiness_result)

        # PID checks as informational when WebSocket OK
        pid_result = _check_pid_file()
        checks.append(pid_result)

        if pid_result.details.get("pid"):
            pid = pid_result.details["pid"]
            process_result = _check_process_alive(pid)
            checks.append(process_result)

            # Uptime check
            uptime_result = _check_daemon_uptime(pid)
            checks.append(uptime_result)
        else:
            checks.append(
                CheckResult(
                    name="process_alive",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no valid PID)",
                )
            )
            checks.append(
                CheckResult(
                    name="daemon_uptime",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no valid PID)",
                )
            )

        # Check for stale locks
        stale_result = _check_stale_locks(config)
        checks.append(stale_result)

        # Calculate overall status
        overall_status = aggregate_status([check.status for check in checks])

        return CategoryResult(
            category="daemon",
            status=overall_status,
            checks=checks,
            message="Daemon healthy (WebSocket responsive)",
        )

    # WebSocket failed - fallback to PID checks
    pid_result = _check_pid_file()
    checks.append(pid_result)

    if pid_result.status == CheckStatus.OK and pid_result.details.get("pid"):
        pid = pid_result.details["pid"]
        process_result = _check_process_alive(pid)
        checks.append(process_result)

        if process_result.status == CheckStatus.OK:
            # Zombie daemon - process alive but transports dead
            checks.append(_check_stale_locks(config))

            return CategoryResult(
                category="daemon",
                status=CheckStatus.ERROR,
                checks=checks,
                message="Zombie daemon (process alive but WebSocket dead)",
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
    stale_result = _check_stale_locks(config)
    checks.append(stale_result)

    return CategoryResult(
        category="daemon",
        status=CheckStatus.INFO,
        checks=checks,
        message="Daemon not running (optional for CLI usage)",
    )
