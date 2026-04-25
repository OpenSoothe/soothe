"""Daemon health check implementation."""

import os

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


def _check_websocket_connectivity(config: SootheConfig | None) -> CheckResult:
    """Check WebSocket transport connectivity (RFC-450)."""
    from soothe.daemon.server import SootheDaemon

    ws_host = config.daemon.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.daemon.transports.websocket.port if config else 8765

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


def _check_http_rest_connectivity(config: SootheConfig | None) -> CheckResult:
    """Check HTTP REST transport connectivity (RFC-450)."""
    import requests

    # Check if HTTP REST enabled
    if not config or not config.daemon.transports.http_rest.enabled:
        return CheckResult(
            name="http_rest_connectivity",
            status=CheckStatus.SKIPPED,
            message="HTTP REST transport disabled",
        )

    http_host = config.daemon.transports.http_rest.host
    http_port = config.daemon.transports.http_rest.port
    health_url = f"http://{http_host}:{http_port}/api/v1/health"

    try:
        response = requests.get(health_url, timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                return CheckResult(
                    name="http_rest_connectivity",
                    status=CheckStatus.OK,
                    message=f"HTTP REST healthy at {http_host}:{http_port}",
                    details={"host": http_host, "port": http_port, "response": data},
                )
    except requests.ConnectionError:
        return CheckResult(
            name="http_rest_connectivity",
            status=CheckStatus.INFO,
            message="HTTP REST not responsive (daemon not running)",
        )
    except requests.Timeout:
        return CheckResult(
            name="http_rest_connectivity",
            status=CheckStatus.WARNING,
            message="HTTP REST timeout (daemon may be overloaded)",
        )
    except Exception as e:
        return CheckResult(
            name="http_rest_connectivity",
            status=CheckStatus.WARNING,
            message=f"HTTP REST error: {e}",
        )

    return CheckResult(
        name="http_rest_connectivity",
        status=CheckStatus.WARNING,
        message="HTTP REST returned unhealthy status",
    )


def _check_http_rest_status(config: SootheConfig | None) -> CheckResult:
    """Fetch daemon status via HTTP REST /api/v1/status endpoint."""
    import requests

    # Check if HTTP REST enabled
    if not config or not config.daemon.transports.http_rest.enabled:
        return CheckResult(
            name="http_rest_status",
            status=CheckStatus.SKIPPED,
            message="HTTP REST transport disabled",
        )

    http_host = config.daemon.transports.http_rest.host
    http_port = config.daemon.transports.http_rest.port
    status_url = f"http://{http_host}:{http_port}/api/v1/status"

    try:
        response = requests.get(status_url, timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            status = data.get("status", "unknown")
            client_count = data.get("client_count", 0)

            return CheckResult(
                name="http_rest_status",
                status=CheckStatus.OK,
                message=f"Daemon status: {status}, clients: {client_count}",
                details={"status": status, "client_count": client_count, "response": data},
            )
    except requests.ConnectionError:
        return CheckResult(
            name="http_rest_status",
            status=CheckStatus.INFO,
            message="HTTP REST not responsive (daemon not running)",
        )
    except Exception as e:
        return CheckResult(
            name="http_rest_status",
            status=CheckStatus.WARNING,
            message=f"HTTP REST status error: {e}",
        )

    return CheckResult(
        name="http_rest_status",
        status=CheckStatus.WARNING,
        message="HTTP REST status check failed",
    )


def _check_daemon_readiness(config: SootheConfig | None) -> CheckResult:
    """Check daemon readiness state via WebSocket handshake (RFC-450)."""
    import asyncio
    import json

    ws_host = config.daemon.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.daemon.transports.websocket.port if config else 8765
    ws_url = f"ws://{ws_host}:{ws_port}"

    try:

        async def handshake() -> dict | None:
            """Perform WebSocket handshake and receive daemon_ready message."""
            import websockets

            async with websockets.connect(ws_url, timeout=2.0) as ws:
                # Receive initial handshake messages (status + daemon_ready)
                for _ in range(2):
                    message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(message)
                    if data.get("type") == "daemon_ready":
                        return data
            return None

        ready_msg = asyncio.run(handshake())
        if ready_msg:
            state = ready_msg.get("state", "unknown")
            status_map = {
                "ready": CheckStatus.OK,
                "degraded": CheckStatus.WARNING,
                "error": CheckStatus.ERROR,
                "starting": CheckStatus.INFO,
                "warming": CheckStatus.INFO,
                "stopped": CheckStatus.INFO,
            }

            return CheckResult(
                name="daemon_readiness",
                status=status_map.get(state, CheckStatus.WARNING),
                message=f"Daemon readiness state: {state}",
                details={"state": state, "message": ready_msg.get("message")},
            )

        return CheckResult(
            name="daemon_readiness",
            status=CheckStatus.WARNING,
            message="No daemon_ready message received",
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


def _check_client_sessions(config: SootheConfig | None) -> CheckResult:
    """Check connected client sessions count."""
    import requests

    # Check if HTTP REST enabled
    if not config or not config.daemon.transports.http_rest.enabled:
        return CheckResult(
            name="client_sessions",
            status=CheckStatus.SKIPPED,
            message="HTTP REST transport disabled",
        )

    http_host = config.daemon.transports.http_rest.host
    http_port = config.daemon.transports.http_rest.port
    status_url = f"http://{http_host}:{http_port}/api/v1/status"

    try:
        response = requests.get(status_url, timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            client_count = data.get("client_count", 0)

            return CheckResult(
                name="client_sessions",
                status=CheckStatus.INFO,
                message=f"Connected clients: {client_count}",
                details={"client_count": client_count},
            )
    except Exception as e:
        return CheckResult(
            name="client_sessions",
            status=CheckStatus.INFO,
            message=f"Client sessions check failed: {e}",
        )

    return CheckResult(
        name="client_sessions",
        status=CheckStatus.INFO,
        message="Client sessions check skipped",
    )


def _check_active_threads(config: SootheConfig | None) -> CheckResult:
    """Check active thread count."""
    import requests

    # Check if HTTP REST enabled
    if not config or not config.daemon.transports.http_rest.enabled:
        return CheckResult(
            name="active_threads",
            status=CheckStatus.SKIPPED,
            message="HTTP REST transport disabled",
        )

    http_host = config.daemon.transports.http_rest.host
    http_port = config.daemon.transports.http_rest.port
    threads_url = f"http://{http_host}:{http_port}/api/v1/threads"

    try:
        response = requests.get(threads_url, params={"status": "running"}, timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            total_threads = data.get("total", 0)
            max_concurrent = config.daemon.max_concurrent_threads if config else 100

            # Check if near limit
            percent = (total_threads / max_concurrent * 100) if max_concurrent > 0 else 0
            if percent > 80:
                return CheckResult(
                    name="active_threads",
                    status=CheckStatus.WARNING,
                    message=f"Active threads near limit: {total_threads}/{max_concurrent}",
                    details={"active_count": total_threads, "max_concurrent": max_concurrent},
                )

            return CheckResult(
                name="active_threads",
                status=CheckStatus.OK,
                message=f"Active threads: {total_threads}/{max_concurrent}",
                details={"active_count": total_threads, "max_concurrent": max_concurrent},
            )
    except Exception as e:
        return CheckResult(
            name="active_threads",
            status=CheckStatus.INFO,
            message=f"Active threads check failed: {e}",
        )

    return CheckResult(
        name="active_threads",
        status=CheckStatus.INFO,
        message="Active threads check skipped",
    )


def _check_queue_depth(config: SootheConfig | None) -> CheckResult:
    """Monitor queue depths for backpressure detection (IG-258)."""
    import requests

    # Check if HTTP REST enabled
    if not config or not config.daemon.transports.http_rest.enabled:
        return CheckResult(
            name="queue_depth",
            status=CheckStatus.SKIPPED,
            message="HTTP REST transport disabled",
        )

    http_host = config.daemon.transports.http_rest.host
    http_port = config.daemon.transports.http_rest.port
    health_url = f"http://{http_host}:{http_port}/api/v1/health"

    try:
        response = requests.get(health_url, timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            queues = data.get("queues", {})

            # Check input queue
            input_queue = queues.get("input_queue", {})
            input_percent = input_queue.get("percent", 0)

            # Check event queues
            event_queues = queues.get("event_queues", {})
            clients_near_capacity = event_queues.get("clients_near_capacity", 0)

            # Determine status based on queue depths
            if input_percent > 80 or clients_near_capacity > 0:
                return CheckResult(
                    name="queue_depth",
                    status=CheckStatus.WARNING,
                    message=f"Queues near capacity (input: {input_percent}% full, {clients_near_capacity} clients near limit)",
                    details={"input_queue": input_queue, "event_queues": event_queues},
                )

            return CheckResult(
                name="queue_depth",
                status=CheckStatus.OK,
                message="Queue depths healthy",
                details={"input_queue": input_queue, "event_queues": event_queues},
            )
    except Exception as e:
        return CheckResult(
            name="queue_depth",
            status=CheckStatus.INFO,
            message=f"Queue depth check failed: {e}",
        )

    return CheckResult(
        name="queue_depth",
        status=CheckStatus.INFO,
        message="Queue depth check skipped",
    )


def _check_stale_locks(config: SootheConfig | None) -> CheckResult:
    """Check for stale PID files and zombie daemon."""
    from soothe.daemon.paths import pid_path
    from soothe.daemon.server import SootheDaemon

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
            ws_host = config.daemon.transports.websocket.host if config else "127.0.0.1"
            ws_port = config.daemon.transports.websocket.port if config else 8765
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


async def check_daemon(config: SootheConfig | None = None) -> CategoryResult:
    """Check daemon health with WebSocket-first priority (RFC-450).

    Uses WebSocket-first logic to prioritize actual daemon responsiveness
    over PID file checks. Falls back to HTTP REST and PID checks if WebSocket fails.

    Args:
        config: SootheConfig instance for transport configuration

    Returns:
        CategoryResult with daemon check results
    """
    checks = []

    # Priority 1: WebSocket connectivity (primary transport)
    ws_result = _check_websocket_connectivity(config)
    checks.append(ws_result)

    if ws_result.status == CheckStatus.OK:
        # WebSocket healthy - run informational checks
        http_result = _check_http_rest_connectivity(config)
        checks.append(http_result)

        http_status_result = _check_http_rest_status(config)
        checks.append(http_status_result)

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

        # Client sessions and active threads
        client_sessions_result = _check_client_sessions(config)
        checks.append(client_sessions_result)

        active_threads_result = _check_active_threads(config)
        checks.append(active_threads_result)

        # Queue depth check (IG-258)
        queue_depth_result = _check_queue_depth(config)
        checks.append(queue_depth_result)

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

    # WebSocket failed - try HTTP REST (secondary transport)
    http_result = _check_http_rest_connectivity(config)
    checks.append(http_result)

    if http_result.status == CheckStatus.OK:
        # HTTP REST healthy but WebSocket failed - degraded
        http_status_result = _check_http_rest_status(config)
        checks.append(http_status_result)

        pid_result = _check_pid_file()
        checks.append(pid_result)

        if pid_result.details.get("pid"):
            pid = pid_result.details["pid"]
            process_result = _check_process_alive(pid)
            checks.append(process_result)
        else:
            checks.append(
                CheckResult(
                    name="process_alive",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no valid PID)",
                )
            )

        checks.append(_check_stale_locks(config))

        return CategoryResult(
            category="daemon",
            status=CheckStatus.WARNING,
            checks=checks,
            message="Daemon degraded (WebSocket failed, HTTP REST responsive)",
        )

    # Both transports failed - fallback to PID checks
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
                message="Zombie daemon (process alive but transports dead)",
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
